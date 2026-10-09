# SPDX-License-Identifier: GPL-3.0-or-later
"""«Registrar como entrada» una capa de un GeoPackage (spec 008, T34; RF-008-07, RF-008-11,
RF-008-52, RF-008-54, RF-008-62; D14 del plan 008; ADR-0025 §2; plan 008 §5.1, §5.4.8 y
§5.4.9).

``core.provenance.importer.import_layer`` (la operación ``core.import_layer``) registra como
entrada una capa o una tabla de un GeoPackage externo o del propio proyecto (una creada desde
QGIS, con ancla de tabla del proyecto) y deja lo importado en ``core_imported_<slug>``, una
copia inmutable: la capa del proyecto no puede ser a la vez fuente e importado. Su importador
(``ImporterDef`` del lector ``core.gpkg_layer``) la reimporta con los ajustes registrados
(``reimport_input``, «Actualizar»): una entrada nueva sustituye a la anterior, que queda con lo
importado intacto; si la capa ya no está, el importador pide los ajustes (``SettingsNeeded``).

Cada prueba usa el proyecto sintético de ``test_registry`` (esquema 2, reloj simulado) con las
fuentes de prueba copiadas en ``fuentes/``, junto a él.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered
from tests.unit.core.inputs.test_registry import (
    ED50,
    ETRS89,
    GPKG,
    NOT_APPLICABLE,
    NOW,
    REASON,
    SESSION,
    InputsCase,
)

importer = import_geoblender("core.provenance.importer")
provenance = import_geoblender("core.provenance")
contract = import_geoblender("core.provenance.contract")
messages = import_geoblender("core.provenance.messages")
orphans = import_geoblender("core.datasets.orphans")
datasets = import_geoblender("core.datasets")
inputs = import_geoblender("core.inputs")
content = import_geoblender("core.content")
events = import_geoblender("core.project.events")
paths = import_geoblender("core.paths")

ProvenanceError = messages.ProvenanceError
UPDATE_REASON = "La propiedad entrega el límite corregido"
LAYER = data.LAYER
SOURCE_TABLE = "zonas_qgis"
NOTES_TABLE = "notas_qgis"
STATE_TABLES = ("gb_input", "gb_input_file", "gb_operation", "gb_operation_io", "gb_dataset",
                "gb_dataset_change", "gb_event", "gb_stale", "gpkg_contents",
                "gpkg_geometry_columns", "gpkg_spatial_ref_sys")
MISSING_TEXT = ("La capa «limites» no está en «Limites_v1.gpkg» (tiene: «limites_2026»): "
                "indique otra vez los ajustes de la importación (la capa) para importar "
                "«Limites_v1».")


def _read_only(path: Path) -> sqlite3.Connection:
    """Una conexión que solo lee una fuente (sin crear nada junto a ella)."""
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _rows(conn: sqlite3.Connection, table: str, columns: str = "*") -> list[Any]:
    return conn.execute(f'SELECT {columns} FROM "{table}" ORDER BY 1').fetchall()


def _rename_layer(path: Path, new: str) -> None:
    """La capa ``limites`` de ``path`` con otro nombre, como la deja GDAL al renombrarla."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute(f'ALTER TABLE "{LAYER}" RENAME TO "{new}"')
        for table in ("gpkg_contents", "gpkg_geometry_columns"):
            conn.execute(f"UPDATE {table} SET table_name = ? WHERE table_name = ?", (new, LAYER))
        conn.execute("COMMIT")
    finally:
        conn.close()


class ImporterCase(InputsCase):
    """El proyecto de ``test_registry`` con las operaciones y el importador de ``core``."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(*contract.CORE_OPERATIONS))
        self.enterContext(registered(*importer.CORE_IMPORTERS))
        self.source = self.sources / data.BOUNDARY_V1

    # --- Ayudas -----------------------------------------------------------------------------

    def state(self) -> list[Any]:
        """Todo lo que la importación escribe en la base: el registro y las tablas."""
        with self.project.read() as conn:
            found = [conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                     for table in STATE_TABLES]
            found.append(conn.execute("SELECT type, name, sql FROM sqlite_master "
                                      "ORDER BY 1, 2").fetchall())
        return found

    def unchanged(self, error: type[BaseException], code: str | None,
                  work: Callable[[], Any]) -> BaseException:
        """``work`` se rechaza sin escribir nada en el proyecto ni junto a la fuente."""
        before = self.state()
        with assert_source_untouched(self.sources), self.assertRaises(error) as caught:
            work()
        if code is not None:
            self.assertEqual(getattr(caught.exception, "code", None), code,
                             str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertTrue(self.project.writable)
        return caught.exception

    def foreign(self, *statements: str, args: tuple[tuple[Any, ...], ...] = ()) -> None:
        """Lo que hace otro programa (QGIS) en el proyecto con su conexión, sin las funciones
        de Geoblender, en una transacción."""
        conn = sqlite3.connect(str(self.project.database_path), isolation_level=None)
        try:
            conn.execute("BEGIN")
            for index, sql in enumerate(statements):
                conn.execute(sql, args[index] if index < len(args) else ())
            conn.execute("COMMIT")
        finally:
            conn.close()

    def qgis_layer(self, table: str = SOURCE_TABLE,
                   parcels: Any = data.PARCELS_V1) -> None:
        """Una capa de polígonos creada en el proyecto desde QGIS (sin registrar)."""
        conn = sqlite3.connect(str(self.project.database_path), isolation_level=None)
        try:
            conn.execute("BEGIN")
            conn.execute(f'CREATE TABLE "{table}" (fid INTEGER PRIMARY KEY AUTOINCREMENT '
                         "NOT NULL, geom POLYGON, codigo TEXT(20), tipo TEXT)")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "srs_id) VALUES (?, 'features', ?, ?)", (table, table, data.EPSG))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POLYGON', ?, 0, "
                         "0)", (table, data.EPSG))
            conn.executemany(f'INSERT INTO "{table}" (geom, codigo, tipo) VALUES (?, ?, ?)',
                             [(data.geometry_blob(ring), code, kind)
                              for code, kind, ring in parcels])
            conn.execute("COMMIT")
        finally:
            conn.close()

    def table_state(self, table: str) -> list[Any]:
        """Lo que es de una tabla del proyecto: su SQL, sus disparadores, su fila de
        ``gpkg_contents`` y sus filas."""
        with self.project.read() as conn:
            return [
                conn.execute("SELECT type, name, sql FROM sqlite_master WHERE tbl_name = ? "
                             "ORDER BY 1, 2", (table,)).fetchall(),
                conn.execute("SELECT * FROM gpkg_contents WHERE table_name = ?",
                             (table,)).fetchall(),
                _rows(conn, table),
            ]

    def unregistered(self) -> tuple[Any, ...]:
        """Las capas y tablas sin registrar que ve el barrido (solo leyendo)."""
        steps = list(orphans.orphan_steps(self.project, write=False))
        return tuple(item for item in steps[-1].result.foreign
                     if item.kind is orphans.ForeignKind.TABLE)

    def operation_row(self, uid: str) -> dict[str, Any]:
        (row,) = self.rows("gb_operation", "uid = ?", (uid,))
        return row

    def protected(self, table: str, input_name: str) -> None:
        """Lo importado no se cambia desde otra conexión (QGIS): el rechazo lo dice."""
        conn = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                               isolation_level=None)
        self.addCleanup(conn.close)
        for sql in (f'UPDATE "{table}" SET tipo = \'otro\'', f'DELETE FROM "{table}"'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError) as caught:
                conn.execute(sql)
            self.assertIn(f"{table}: es lo importado de la entrada «{input_name}»: no se "
                          "modifica", str(caught.exception))

    def import_v1(self) -> Any:
        with assert_source_untouched(self.sources):
            return importer.import_layer(self.project, LAYER, source=self.source,
                                         received_at="2026-09-24", received_from="La propiedad")


class ExternalLayerTest(ImporterCase):
    def test_external_layer_is_an_input_with_its_imported_copy_and_operation(self) -> None:
        """RF-008-07, RF-008-52 (D14): registrar la capa «limites» de ``Limites_v1.gpkg``
        (fuera del proyecto) deja una entrada con su fichero, su huella, su capa, sus CRS (el
        horizontal, el que declara el fichero; el vertical, «no aplica» en una capa plana), sus
        ajustes, sus hashes (los del lector de ``core``, como cualquier importador) y su
        entrega; lo importado, en ``core_imported_limites_v1``: una copia de sus entidades
        (mismos ``fid``) con el mismo hash de datos, protegida, de la operación
        ``core.import_layer``. La fuente no cambia y nada guarda una ruta absoluta."""
        with closing(_read_only(self.source)) as conn:
            expected_rows = _rows(conn, LAYER, "fid, geom, codigo, tipo")
        expected = self.boundary()

        result = self.import_v1()

        record = result.input
        self.assertFalse(result.reused)
        self.assertEqual(result.uid, result.operation_uid)
        self.assertEqual((record.name, record.kind, record.module, record.reader, record.layer),
                         ("Limites_v1", "vector", "core", GPKG, LAYER))
        self.assertEqual((dict(record.crs_h), dict(record.crs_v)), (ETRS89, NOT_APPLICABLE))
        self.assertEqual(dict(record.settings), {"layer": LAYER})
        self.assertEqual(record.content_settings_keys, ())
        self.assertEqual(record.digest, expected.digest)
        self.assertEqual(record.settings_sha256, expected.settings_sha256)
        self.assertEqual((record.received_at, record.received_from), ("2026-09-24",
                                                                       "La propiedad"))
        self.assertEqual((record.registered_by, record.registered_at), (SESSION.user_host, NOW))
        self.assertEqual(record.operation_uid, result.operation_uid)
        self.assertEqual(record.original, "not_applicable")
        (source_file,) = record.files
        self.assertEqual(source_file.source, expected.files[0])
        self.assertEqual((source_file.sha256, source_file.size, source_file.mtime_ns),
                         (expected.file_prints[0].sha256, expected.file_prints[0].size,
                          expected.file_prints[0].mtime_ns))
        dataset = result.dataset
        self.assertEqual(result.table, "core_imported_limites_v1")
        self.assertEqual(
            (dataset.name, dataset.module, dataset.kind, dataset.store, dataset.locator,
             dataset.reader, dataset.input_uid, dataset.immutable, dataset.crs_epsg,
             dataset.operation_uid, dataset.status),
            ("core_imported_limites_v1", "core", "vector", "gpkg", "core_imported_limites_v1",
             GPKG, record.uid, True, data.EPSG, result.operation_uid, "current"),
        )
        self.assertEqual(dataset.content_sha256, content.content_sha256(
            "vector", {}, record.data_sha256))
        operation = self.operation_row(result.operation_uid)
        self.assertEqual(
            (operation["op_type"], operation["module"], operation["status"],
             operation["executor"], operation["repeatable"], operation["supersedes_uid"]),
            ("core.import_layer", "core", "done", "blender", 0, None),
        )
        self.assertEqual(operation["settings"], '{"layer":"limites","source":{"anchor":'
                         f'"{source_file.anchor}","path":"{source_file.path}"}}}}')
        self.assertEqual(
            [(row["direction"], row["item_kind"], row["item_uid"], row["role"])
             for row in self.rows("gb_operation_io", "operation_uid = ?",
                                  (result.operation_uid,))],
            [("out", "dataset", dataset.uid, "imported")],
        )
        with self.project.read() as conn:
            self.assertEqual(_rows(conn, result.table, "fid, geom, codigo, tipo"),
                             expected_rows)
            self.assertEqual(conn.execute(
                "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?",
                (result.table,)).fetchone(), ("features", data.EPSG))
            self.assertEqual(conn.execute(
                "SELECT column_name, geometry_type_name, srs_id, z, m FROM "
                "gpkg_geometry_columns WHERE table_name = ?", (result.table,)).fetchone(),
                ("geom", "POLYGON", data.EPSG, 0, 0))
        self.protected(result.table, "Limites_v1")
        (event,) = self.logged(events.EventKind.INPUT_REGISTERED)
        self.assertEqual(event.entity_uid, record.uid)
        self.assertEqual(result.text(), "Capa «limites» registrada como entrada «Limites_v1»; "
                                        "lo importado, en «core_imported_limites_v1».")
        self.assertIn("core_imported_limites_v1", result.text("en"))
        stored = [self.rows(table) for table in ("gb_input", "gb_input_file", "gb_operation",
                                                 "gb_dataset", "gb_event")]
        self.assertEqual(paths.find_absolute_paths(stored), [])
        self.assertEqual(self.unregistered(), ())

    def test_same_layer_again_is_reused_and_other_settings_substitute(self) -> None:
        """RF-008-54, RF-008-11: la misma capa otra vez, con los mismos ajustes, no se
        duplica: la importación queda cancelada con el aviso de la spec §8 y su evento; con
        otro CRS declarado (ED50), se rechaza sin escribir nada hasta que se diga a qué entrada
        sustituye y por qué, y entonces la sustituye: la anterior y lo importado de ella quedan
        como historia y lo importado nuevo toma su nombre con otra tabla."""
        first = self.import_v1()
        before = (self.rows("gb_input"), self.rows("gb_dataset"))

        again = importer.import_layer(self.project, LAYER, source=self.source)

        self.assertTrue(again.reused)
        self.assertEqual(again.input.uid, first.input.uid)
        self.assertIsNone(again.dataset)
        self.assertIsNone(again.table)
        reuse_text = ("La entrada «Limites_v1» ya está registrada con el mismo contenido "
                      "(05/10/2026).")
        self.assertEqual(again.text(), reuse_text)
        cancelled = self.operation_row(again.operation_uid)
        self.assertEqual((cancelled["status"], cancelled["status_reason"]),
                         ("cancelled", reuse_text))
        self.assertEqual(len(self.logged(events.EventKind.INPUT_REUSED)), 1)
        self.assertEqual((self.rows("gb_input"), self.rows("gb_dataset")), before)

        error = self.unchanged(ProvenanceError, "core.input_substitution_required",
                               lambda: importer.import_layer(self.project, LAYER,
                                                             source=self.source, crs_h=ED50))
        self.assertIn("EPSG:25830 → EPSG:23030", str(error))
        self.unchanged(ProvenanceError, "core.input_supersede_reason_missing",
                       lambda: importer.import_layer(self.project, LAYER, source=self.source,
                                                     crs_h=ED50,
                                                     previous_uid=first.input.uid, reason=" "))

        replaced = importer.import_layer(self.project, LAYER, source=self.source, crs_h=ED50,
                                         previous_uid=first.input.uid, reason=REASON)

        self.assertEqual(dict(replaced.input.crs_h), ED50)
        self.assertEqual(replaced.input.previous_uid, first.input.uid)
        old = self.read(lambda conn: inputs.get(conn, first.input.uid))
        self.assertEqual((old.status, old.status_reason), ("superseded", REASON))
        self.assertEqual((replaced.dataset.name, replaced.table),
                         ("core_imported_limites_v1", "core_imported_limites_v1_2"))
        old_dataset = self.read(lambda conn: datasets.get(conn, first.dataset.uid))
        self.assertEqual((old_dataset.status, old_dataset.content_sha256),
                         ("superseded", first.dataset.content_sha256))
        self.assertEqual(replaced.dataset.content_sha256, first.dataset.content_sha256)
        self.assertEqual(self.operation_row(replaced.operation_uid)["supersedes_uid"],
                         first.operation_uid)
        self.assertEqual(self.operation_row(first.operation_uid)["superseded_by"],
                         replaced.operation_uid)
        self.unchanged(ProvenanceError, "core.input_superseded",
                       lambda: importer.import_layer(self.project, LAYER, source=self.source,
                                                     previous_uid=first.input.uid,
                                                     reason=REASON))


class ProjectLayerTest(ImporterCase):
    def test_project_layer_created_in_qgis_is_registered_with_a_table_anchor(self) -> None:
        """RF-008-62, RF-008-07, RF-008-52 (spec §8, «Capa nueva creada en el proyecto desde
        QGIS»): una capa y una tabla creadas en el proyecto desde otra conexión están sin
        registrar; registrarlas deja cada una como entrada con ancla de tabla del proyecto
        (su ``last_change``, sin tamaño ni fecha) y lo importado en una copia protegida, y ya
        no están sin registrar. La capa del proyecto no se toca: ni sus filas, ni su SQL, ni
        sus disparadores, ni su fila de ``gpkg_contents``. Editada luego en QGIS, reimportarla
        sustituye la entrada sin tocar lo importado antes."""
        self.qgis_layer()
        self.foreign(f'CREATE TABLE "{NOTES_TABLE}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                     "NULL, nota TEXT, valor DOUBLE, fecha DATE)",
                     f'INSERT INTO "{NOTES_TABLE}" (fid, nota, valor, fecha) VALUES '
                     "(7, 'revisar talud', 1.5, '2026-09-30'), (9, 'sin cambios', NULL, NULL)",
                     "INSERT INTO gpkg_contents (table_name, data_type, identifier) "
                     f"VALUES ('{NOTES_TABLE}', 'attributes', 'Notas de campo')")
        self.assertEqual(self.unregistered(), (
            orphans.Foreign(orphans.ForeignKind.TABLE, NOTES_TABLE, True),
            orphans.Foreign(orphans.ForeignKind.TABLE, SOURCE_TABLE, True),
        ))
        error = self.unchanged(contract.SettingsNeeded, "core.import_layer_missing",
                               lambda: importer.import_layer(self.project, "zonas"))
        self.assertEqual(dict(error.choices), {"layer": (NOTES_TABLE, SOURCE_TABLE)})
        layer_before = self.table_state(SOURCE_TABLE)
        changed = self.read(lambda conn: conn.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name = ?",
            (SOURCE_TABLE,)).fetchone()[0])

        with assert_source_untouched(self.sources):
            layer = importer.import_layer(self.project, SOURCE_TABLE)
            notes = importer.import_layer(self.project, NOTES_TABLE, name="Notas de campo",
                                          source=self.project.database_path)

        self.assertEqual(self.table_state(SOURCE_TABLE), layer_before)
        record = layer.input
        self.assertEqual((record.name, record.kind, record.layer, dict(record.crs_h),
                          dict(record.crs_v)),
                         (SOURCE_TABLE, "vector", SOURCE_TABLE, ETRS89, NOT_APPLICABLE))
        (source_file,) = record.files
        self.assertEqual(
            (source_file.anchor, source_file.path, source_file.size, source_file.mtime_ns,
             source_file.last_change, source_file.sha256),
            ("project_table", SOURCE_TABLE, None, None, changed, record.data_sha256),
        )
        self.assertEqual(record.data_sha256, self.boundary().digest.data_sha256)
        self.assertEqual((layer.table, layer.dataset.immutable, layer.dataset.input_uid),
                         ("core_imported_zonas_qgis", True, record.uid))
        self.protected(layer.table, SOURCE_TABLE)
        self.assertEqual((notes.input.name, notes.input.kind, dict(notes.input.crs_h),
                          dict(notes.input.crs_v), notes.input.files[0].anchor, notes.table,
                          notes.dataset.kind, notes.dataset.crs_epsg),
                         ("Notas de campo", "table", NOT_APPLICABLE, NOT_APPLICABLE,
                          "project_table", "core_imported_notas_de_campo", "table", None))
        with self.project.read() as conn:
            self.assertEqual(_rows(conn, notes.table, "fid, nota, valor, fecha"), [
                (7, "revisar talud", 1.5, "2026-09-30"), (9, "sin cambios", None, None)])
        self.assertEqual(notes.dataset.content_sha256, content.content_sha256(
            "table", {}, notes.input.data_sha256))
        self.assertEqual(self.unregistered(), ())
        error = self.unchanged(contract.SettingsNeeded, "core.import_layer_missing",
                               lambda: importer.import_layer(self.project, "zonas"))
        self.assertEqual((dict(error.choices), error.values["layers"]), ({"layer": ()}, "—"))

        # Editada en QGIS: reimportarla da otra entrada y lo importado antes queda intacto.
        self.foreign(f'UPDATE "{SOURCE_TABLE}" SET geom = ? WHERE codigo = ?',
                     args=((data.geometry_blob(data.PARCELS_V2[1][2]), "P-02"),))
        copy_before = self.table_state(layer.table)
        updated = provenance.reimport_input(self.project, record.uid, UPDATE_REASON)
        self.assertEqual((updated.input.previous_uid, updated.input.layer, updated.table),
                         (record.uid, SOURCE_TABLE, "core_imported_zonas_qgis_2"))
        self.assertEqual(updated.input.data_sha256, self.boundary(
            data.BOUNDARY_V2).digest.data_sha256)
        self.assertEqual(self.table_state(layer.table), copy_before)

    def test_layer_edited_while_it_is_imported_is_registered_as_copied(self) -> None:
        """RF-008-07, RF-008-52: si otro programa (QGIS) edita la capa del proyecto después de
        leerla para clasificarla y antes de copiarla, la entrada y lo importado son los de la
        capa que se copia (la editada), nunca una mezcla."""
        self.qgis_layer()
        real = importer._run

        def edited_meanwhile(*args: Any) -> Any:
            self.foreign(f'UPDATE "{SOURCE_TABLE}" SET geom = ? WHERE codigo = ?',
                         args=((data.geometry_blob(data.PARCELS_V2[1][2]), "P-02"),))
            return real(*args)

        with mock.patch.object(importer, "_run", side_effect=edited_meanwhile):
            result = importer.import_layer(self.project, SOURCE_TABLE)

        self.assertEqual(result.input.data_sha256,
                         self.boundary(data.BOUNDARY_V2).digest.data_sha256)
        with self.project.read() as conn:
            self.assertEqual(_rows(conn, result.table), _rows(conn, SOURCE_TABLE))


class ReimportTest(ImporterCase):
    def test_reimport_with_registered_settings_supersedes_the_input(self) -> None:
        """RF-008-11, RF-008-52 (spec §8, «Actualizar dos veces una entrada»): con la fuente
        cambiada (el límite redibujado), reimportarla con los ajustes registrados (la capa y
        los CRS declarados) y un motivo registra una entrada nueva que sustituye a la anterior,
        con la misma capa, su contenido nuevo y lo importado en otra tabla con el mismo
        nombre de dato; la anterior queda sustituida con el motivo, y lo importado de ella,
        intacto y protegido, con su sucesor. Sin motivo, o de una entrada ya sustituida, se
        rechaza sin escribir nada; la fuente no cambia."""
        first = self.import_v1()
        copy_before = self.read(lambda conn: _rows(conn, first.table))
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, self.source)
        self.unchanged(ProvenanceError, "core.input_supersede_reason_missing",
                       lambda: provenance.reimport_input(self.project, first.input.uid, ""))

        with assert_source_untouched(self.sources):
            updated = provenance.reimport_input(self.project, first.input.uid, UPDATE_REASON)

        record = updated.input
        self.assertEqual(
            (record.name, record.layer, dict(record.crs_h), dict(record.crs_v),
             record.previous_uid, dict(record.settings)),
            ("Limites_v1", LAYER, ETRS89, NOT_APPLICABLE, first.input.uid, {"layer": LAYER}),
        )
        self.assertEqual(record.digest, self.boundary().digest)
        self.assertNotEqual(record.data_sha256, first.input.data_sha256)
        old = self.read(lambda conn: inputs.get(conn, first.input.uid))
        self.assertEqual((old.status, old.status_reason), ("superseded", UPDATE_REASON))
        self.assertEqual((updated.dataset.name, updated.table),
                         ("core_imported_limites_v1", "core_imported_limites_v1_2"))
        self.assertEqual(self.read(lambda conn: _rows(conn, first.table)), copy_before)
        self.protected(first.table, "Limites_v1")
        successor = self.read(lambda conn: datasets.successor(conn, first.dataset.uid))
        self.assertEqual(successor.uid, updated.dataset.uid)
        self.assertEqual(self.operation_row(updated.operation_uid)["supersedes_uid"],
                         first.operation_uid)
        self.assertEqual(len(self.logged(events.EventKind.INPUT_UPDATED)), 1)
        self.write(lambda conn: inputs.discard(conn, self.project, record.uid,
                                               "Importación equivocada"))
        for key, code in ((first.input.uid, "core.input_superseded"),
                          (record.uid, "core.input_discarded"),
                          ("no-existe", "core.input_unknown")):
            with self.subTest(key=key):
                self.unchanged(ProvenanceError, code, lambda key=key: provenance.reimport_input(
                    self.project, key, UPDATE_REASON))

    def test_missing_layer_asks_for_the_settings(self) -> None:
        """RF-008-11 (spec §8, «Actualizar con una columna que el cliente renombró»): si la
        capa registrada ya no está en la fuente, el importador pide los ajustes con un error
        claro (``SettingsNeeded``: la capa, con las que tiene la fuente) sin escribir nada; con
        la capa nueva, reimporta. Importar por primera vez una capa que no está, igual."""
        first = self.import_v1()
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, self.source)
        _rename_layer(self.source, "limites_2026")

        error = self.unchanged(contract.SettingsNeeded, "core.import_layer_missing",
                               lambda: provenance.reimport_input(self.project, first.input.uid,
                                                                 UPDATE_REASON))
        self.assertIsInstance(error, ProvenanceError)
        self.assertEqual(str(error), MISSING_TEXT)
        self.assertEqual(error.needed, ("layer",))
        self.assertEqual(dict(error.choices), {"layer": ("limites_2026",)})
        self.unchanged(contract.SettingsNeeded, "core.import_layer_missing",
                       lambda: importer.import_layer(self.project, "otra", source=self.source))

        with assert_source_untouched(self.sources):
            updated = provenance.reimport_input(self.project, first.input.uid, UPDATE_REASON,
                                                settings={"layer": "limites_2026"})

        self.assertEqual((updated.input.layer, dict(updated.input.settings),
                          updated.input.previous_uid),
                         ("limites_2026", {"layer": "limites_2026"}, first.input.uid))
        self.assertEqual(updated.input.data_sha256, self.boundary(
            data.BOUNDARY_V2).digest.data_sha256)
        with self.assertRaises(ValueError):
            provenance.reimport_input(self.project, updated.input.uid, UPDATE_REASON,
                                      settings={"capa": "limites"})

    def test_update_matching_another_input_is_refused(self) -> None:
        """RF-008-54, RF-008-11: si al actualizar una entrada su fuente tiene ya el contenido
        y los ajustes de otra entrada activa, no se duplica: se rechaza con el aviso de la
        spec §8, sin escribir nada."""
        first = self.import_v1()
        importer.import_layer(self.project, LAYER, source=self.sources / data.BOUNDARY_V2)
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, self.source)
        error = self.unchanged(ProvenanceError, "core.input_reused",
                               lambda: provenance.reimport_input(self.project, first.input.uid,
                                                                 UPDATE_REASON))
        self.assertEqual(str(error), "La entrada «Limites_v2» ya está registrada con el mismo "
                                     "contenido (05/10/2026).")

    def test_update_calls_the_importer_of_the_reader_of_the_input(self) -> None:
        """RF-008-11 (ADR-0025 §2): «Actualizar» llama al importador registrado del lector de
        la entrada (sin versión) con la entrada, el motivo, los ajustes que pidió el
        importador y la entrega nueva, y devuelve lo que él devuelve; sin motivo no lo llama
        ni escribe nada."""
        calls: list[Any] = []

        def reimport(request: Any) -> str:
            calls.append(request)
            return "reimportada"

        record = self.register(self.simple("planos", "document", NOT_APPLICABLE,
                                           NOT_APPLICABLE))
        with registered(contract.ImporterDef("test.source", reimport)):
            result = provenance.reimport_input(
                self.project, "planos", "  La propiedad entrega otra versión  ",
                settings={"hoja": 2}, received_at="2026-10-01", received_from="La propiedad")
            self.unchanged(ProvenanceError, "core.input_supersede_reason_missing",
                           lambda: provenance.reimport_input(self.project, record.uid, "  "))
        self.assertEqual(result, "reimportada")
        (request,) = calls
        self.assertEqual(
            (request.project, request.input_uid, request.reason, dict(request.settings),
             request.received_at, request.received_from),
            (self.project, record.uid, "La propiedad entrega otra versión", {"hoja": 2},
             "2026-10-01", "La propiedad"),
        )

    def test_unreachable_source_and_unregistered_importer(self) -> None:
        """RF-008-11, RF-008-13: una fuente que ya no está no se reimporta (se dice cuál) y,
        sin el importador de su lector registrado, tampoco; nada se escribe."""
        first = self.import_v1()
        self.source.unlink()
        error = self.unchanged(ProvenanceError, "core.reimport_source_missing",
                               lambda: provenance.reimport_input(self.project, first.input.uid,
                                                                 UPDATE_REASON))
        self.assertEqual(str(error), "No se encuentra la fuente de la entrada «Limites_v1» "
                                     f"({first.input.files[0].path}): no se puede reimportar.")
        contract.unregister_importer("core.gpkg_layer")
        self.addCleanup(contract.register_importer, importer.CORE_IMPORTERS[0])
        self.unchanged(ProvenanceError, "core.importer_unregistered",
                       lambda: provenance.reimport_input(self.project, first.input.uid,
                                                         UPDATE_REASON))


class RejectTest(ImporterCase):
    def test_what_cannot_be_registered_is_rejected_without_writing(self) -> None:
        """RF-008-07, RF-008-62, RF-008-14 (constitución, principio 6): sin escribir nada en
        el proyecto ni junto a la fuente, se rechaza un fichero que no es un GeoPackage, una
        capa de teselas, una tabla que ya es un dato del proyecto o interna, una capa con
        cotas sin su CRS vertical declarado (nunca se supone) y todo en solo lectura."""
        self.foreign("INSERT INTO gpkg_contents (table_name, data_type, identifier) "
                     "VALUES ('teselas', 'tiles', 'Teselas')",
                     "CREATE TABLE teselas (id INTEGER PRIMARY KEY, zoom_level INTEGER)")
        three_d = self.sources / "Limites_3d.gpkg"
        shutil.copyfile(self.source, three_d)
        conn = sqlite3.connect(str(three_d), isolation_level=None)
        conn.execute("UPDATE gpkg_geometry_columns SET z = 1")
        conn.close()
        first = self.import_v1()
        report = self.sources / data.REPORT
        cases = (
            ("core.gpkg_not_sqlite", lambda: importer.import_layer(self.project, LAYER,
                                                                    source=report)),
            ("core.import_layer_kind", lambda: importer.import_layer(self.project, "teselas")),
            ("core.import_layer_dataset", lambda: importer.import_layer(self.project,
                                                                         first.table)),
            ("core.import_layer_dataset", lambda: importer.import_layer(self.project,
                                                                         "gb_input")),
            ("core.input_crs_missing", lambda: importer.import_layer(self.project, LAYER,
                                                                      source=three_d)),
        )
        for code, work in cases:
            with self.subTest(code=code):
                self.unchanged(Exception, code, work)
        self.assertEqual(str(self.unchanged(ProvenanceError, "core.import_layer_kind",
                                            cases[1][1])),
                         "«teselas» de «project.gpkg» es de tipo «tiles»: solo se registran "
                         "como entrada capas de entidades y tablas.")
        before = self.state()
        with (mock.patch.object(type(self.project), "writable", property(lambda _s: False)),
              assert_source_untouched(self.sources),
              self.assertRaises(ProvenanceError) as caught):
            importer.import_layer(self.project, LAYER, source=self.sources / data.BOUNDARY_V2)
        self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(self.state(), before)

    def test_a_copy_without_the_content_of_the_input_is_not_registered(self) -> None:
        """RF-008-52, RF-008-19: si la copia de lo importado no tuviera el contenido de la
        entrada (aquí, un SRS que se pierde al copiar), no se registra nada de ella: ni la
        entrada, ni lo importado, ni su tabla; la operación queda «fallida» con el motivo."""
        before = (self.rows("gb_input"), self.rows("gb_dataset"))
        with (mock.patch.object(importer, "_project_srs", return_value=-1),
              self.assertRaises(RuntimeError)):
            importer.import_layer(self.project, LAYER, source=self.source)
        self.assertEqual((self.rows("gb_input"), self.rows("gb_dataset")), before)
        (failed,) = self.rows("gb_operation", "op_type = 'core.import_layer'")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("no tiene el contenido de la entrada «Limites_v1»",
                      failed["status_reason"])
        with self.project.read() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE "
                                           "'core_imported%'").fetchone())

    def test_names_and_api(self) -> None:
        """RF-008-62 (D14; ADR-0025 §2): lo importado va a ``core_imported_<slug>`` (el
        nombre de la entrada en minúsculas, sin tildes y con «_»); ``core.provenance``
        reexporta el importador y su petición; el importador de ``core`` es el del lector
        ``core.gpkg_layer``."""
        for name, expected in (("Limites_v1", "core_imported_limites_v1"),
                               ("Límites 2026 (corregido)", "core_imported_limites_2026_corregido"),
                               ("Señales/ñandú", "core_imported_senales_nandu"),
                               ("—", "core_imported_capa"),
                               ("x" * 80, "core_imported_" + "x" * 40)):
            with self.subTest(name=name):
                self.assertEqual(importer.imported_name(name), expected)
        (defn,) = importer.CORE_IMPORTERS
        self.assertEqual((defn.reader_id, defn.reimport), ("core.gpkg_layer",
                                                           importer.reimport_layer))
        for name in ("import_layer", "reimport_input", "LayerImport", "CORE_IMPORTERS"):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(importer, name))
        for name in ("ReimportRequest", "SettingsNeeded"):
            with self.subTest(name=name):
                self.assertIs(getattr(provenance, name), getattr(contract, name))
        request = contract.ReimportRequest(self.project, "uid", "motivo",
                                           settings={"layer": "x"})
        self.assertEqual(dict(request.settings), {"layer": "x"})
        with self.assertRaises(TypeError):
            request.settings["layer"] = "y"  # type: ignore[index]
        error = contract.SettingsNeeded("core.import_layer_missing", needed=["layer"],
                                        choices={"layer": ["a", "b"]}, layer="x", source="y",
                                        layers="«a», «b»", name="z")
        self.assertEqual((error.needed, dict(error.choices), error.code),
                         (("layer",), {"layer": ("a", "b")}, "core.import_layer_missing"))

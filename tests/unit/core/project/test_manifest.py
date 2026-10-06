# SPDX-License-Identifier: GPL-3.0-or-later
"""Cabecera del proyecto, ``manifest.json`` (spec 002, T12; RF-002-05, RF-002-06,
RF-002-18; plan 002 §5.2 y §5.4; formato-proyecto §2).

La fuente de verdad es ``project.gpkg``: la cabecera es una copia legible que se
reescribe desde la base de datos, de forma atómica (``manifest.json.tmp-<sesión>``,
``fsync`` y ``os.replace``), y al abrir se compara con ella. Si no coinciden en
identidad, CRS (horizontal o vertical) u GeoOrigin, el proyecto no abre y se muestran los
dos valores; si solo difieren las fechas, la versión de Geoblender o la BD registra una
migración que la cabecera no tiene, se regenera desde la BD.
"""

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

manifest = import_geoblender("core.project.manifest")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
paths = import_geoblender("core.paths")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VCRS = CATALOG.vertical(5782)
SESSION_UID = "00000000-0000-4000-8000-000000000001"
CREATED = "2026-10-05T08:12:44.000Z"
MODIFIED = "2026-10-05T17:03:10.000Z"
# Los campos de manifest.json, esquema 1: la lista cerrada de formato-proyecto §2, en su
# orden (convergencia, T43).
TOP_KEYS = (
    "format", "schema_version", "min_reader_schema", "geoblender_version", "created_with",
    "project_uid", "name", "crs", "geo_origin", "grid_step_m", "created_at", "modified_at",
    "stores", "inventory", "checkout",
)
CRS_KEYS = ("epsg", "name", "wkt", "vertical")
VERTICAL_KEYS = ("epsg", "name", "note")
ORIGIN_KEYS = ("x0", "y0", "z0")
STORE_KEYS = ("path", "gpkg_version")


def _record(**changes: object):
    values = {
        "uid": "00000000-0000-4000-8000-0000000000aa",
        "name": "Cantera Prueba",
        "schema_version": 1,
        "min_reader_schema": 1,
        "created_with": "0.1.0",
        "last_written_with": "0.1.0",
        "crs_epsg": CRS.epsg,
        "crs_name": CRS.name,
        "crs_wkt": CRS.wkt2,
        "vcrs_epsg": VCRS.epsg,
        "vcrs_name": VCRS.name,
        "vcrs_wkt": VCRS.wkt2,
        "vcrs_note": None,
        "origin_x": 700_000,
        "origin_y": 4_400_000,
        "origin_z": 0,
        "grid_step_m": 1.0,
        "window_xmin": 699_500.0,
        "window_ymin": 4_399_500.0,
        "window_xmax": 700_501.0,
        "window_ymax": 4_400_501.0,
        "created_at": CREATED,
        "modified_at": MODIFIED,
    }
    values.update(changes)
    return model.ProjectRecord(**values)


def _local_record():
    return _record(
        vcrs_epsg=None, vcrs_name="Referencia local", vcrs_wkt=None, vcrs_note="NP-0 del plano 3"
    )


def _data(record=None) -> dict:
    return manifest.manifest_from_record(record or _record()).to_dict()


def _without(data: dict, dotted: str) -> dict:
    result = copy.deepcopy(data)
    node = result
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[part]
    del node[last]
    return result


def _with(data: dict, dotted: str, value: object) -> dict:
    result = copy.deepcopy(data)
    node = result
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[part]
    node[last] = value
    return result


class ParseTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        """RF-002-06, RF-002-18: la cabecera que sale de la BD se escribe y se vuelve a
        leer igual; lleva el formato, el CRS con su vertical, el GeoOrigin en enteros y
        ninguna ruta absoluta; UTF-8 sin BOM y LF; no deja el temporal."""
        for record in (_record(), _local_record()):
            with self.subTest(vertical=record.vcrs_name), project_tmp() as tmp:
                header = manifest.manifest_from_record(record)
                manifest.write_manifest(tmp, header, SESSION_UID)
                self.assertEqual(manifest.read_manifest(tmp), header)
                raw = (tmp / "manifest.json").read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r\n", raw)
                data = json.loads(raw.decode("utf-8"))
                self.assertEqual(data["format"], "geoblender-project")
                self.assertEqual(data["geo_origin"], {"x0": 700_000, "y0": 4_400_000, "z0": 0})
                self.assertEqual(data["crs"]["epsg"], 25830)
                self.assertEqual(data["crs"]["wkt"], CRS.wkt2)
                self.assertEqual(data["crs"]["vertical"]["epsg"], record.vcrs_epsg)
                self.assertEqual(data["crs"]["vertical"]["note"], record.vcrs_note)
                self.assertEqual(
                    data["stores"]["project"], {"path": "project.gpkg", "gpkg_version": "1.4.0"}
                )
                self.assertEqual(data["inventory"], [])
                self.assertIsNone(data["checkout"])
                self.assertEqual(paths.find_absolute_paths(data), [])
                self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["manifest.json"])

    def test_exact_keys(self) -> None:
        """RF-002-05, RF-002-06: la cabecera que se escribe lleva exactamente los campos de
        formato-proyecto §2 (lista cerrada), ni uno más ni uno menos, en el primer nivel, en
        ``crs``, ``crs.vertical``, ``geo_origin`` y ``stores`` (esquema 1: solo
        ``project``, con ``path`` y ``gpkg_version``), también con una referencia vertical
        local y en una copia local (``checkout``) (convergencia, T43)."""
        checkout = {"session_uid": SESSION_UID, "base": {}, "at": CREATED,
                    "by": "prueba@PC-PRUEBA-A"}
        previous = manifest.parse_manifest(_with(_data(), "checkout", checkout))
        headers = (
            manifest.manifest_from_record(_record()),
            manifest.manifest_from_record(_local_record()),
            manifest.manifest_from_record(_record(), previous=previous),
        )
        for header in headers:
            with self.subTest(vertical=header.vcrs_name, copia=header.checkout is not None), \
                    project_tmp() as tmp:
                manifest.write_manifest(tmp, header, SESSION_UID)
                data = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(list(data), list(TOP_KEYS))
                self.assertEqual(sorted(data["crs"]), sorted(CRS_KEYS))
                self.assertEqual(sorted(data["crs"]["vertical"]), sorted(VERTICAL_KEYS))
                self.assertEqual(sorted(data["geo_origin"]), sorted(ORIGIN_KEYS))
                self.assertEqual(sorted(data["stores"]), ["project"])
                self.assertEqual(sorted(data["stores"]["project"]), sorted(STORE_KEYS))

    def test_missing_fields_are_named(self) -> None:
        """RF-002-05: una cabecera sin ``crs``, sin ``geo_origin`` o sin otra parte
        obligatoria no se acepta: el error nombra el campo que falta."""
        data = _data()
        for dotted in (
            "crs",
            "geo_origin",
            "project_uid",
            "schema_version",
            "crs.epsg",
            "crs.wkt",
            "crs.vertical",
            "crs.vertical.name",
            "geo_origin.x0",
            "geo_origin.z0",
        ):
            with self.subTest(campo=dotted):
                with self.assertRaises(errors.ProjectError) as caught:
                    manifest.parse_manifest(_without(data, dotted))
                self.assertEqual(caught.exception.code, "core.manifest_field_missing")
                self.assertEqual(caught.exception.field, dotted)
                self.assertIn(dotted, str(caught.exception))

    def test_invalid_values_are_named(self) -> None:
        """RF-002-05: un valor de la cabecera que no vale (otro formato, un GeoOrigin con
        decimales o que no es múltiplo de 100, una referencia local sin descripción, una
        fecha sin «Z», una ruta absoluta) se rechaza con el campo y el valor."""
        data = _data()
        cases = {
            "format": "otra-cosa",
            "schema_version": 0,
            "geo_origin.x0": 700_000.5,
            "geo_origin.y0": 4_400_050,
            "geo_origin.z0": True,
            "crs.epsg": "25830",
            "crs.vertical.note": None,
            "created_at": "2026-10-05 08:12:44",
            "grid_step_m": "1",
            "stores.project.path": str(Path.cwd().anchor) + "datos/project.gpkg",
            "inventory": {},
        }
        local = _data(_local_record())
        for dotted, value in cases.items():
            source = local if dotted == "crs.vertical.note" else data
            with self.subTest(campo=dotted):
                with self.assertRaises(errors.ProjectError) as caught:
                    manifest.parse_manifest(_with(source, dotted, value))
                self.assertEqual(caught.exception.code, "core.manifest_field_invalid")
                self.assertEqual(caught.exception.field, dotted)

    def test_file_missing_or_unreadable(self) -> None:
        """RF-002-05: sin ``manifest.json``, o si no es JSON, el proyecto no abre y el
        error lo dice."""
        with project_tmp() as tmp:
            with self.assertRaises(errors.ProjectError) as caught:
                manifest.read_manifest(tmp)
            self.assertEqual(caught.exception.code, "core.manifest_missing")
            (tmp / "manifest.json").write_text("{ no es json", encoding="utf-8")
            with self.assertRaises(errors.ProjectError) as caught:
                manifest.read_manifest(tmp)
            self.assertEqual(caught.exception.code, "core.manifest_unreadable")


class CompareTest(unittest.TestCase):
    def test_consistent(self) -> None:
        """RF-002-05: la cabecera que sale de la BD coincide con ella."""
        record = _record()
        check = manifest.compare(manifest.manifest_from_record(record), record)
        self.assertEqual(check.status, manifest.ManifestStatus.CONSISTENT)
        self.assertEqual(check.differences, ())

    def test_identity_crs_or_origin_differ(self) -> None:
        """RF-002-05: si la cabecera y la BD difieren en identidad, CRS horizontal o
        vertical u GeoOrigin, el resultado es INCONSISTENT y el error muestra los dos
        valores de cada campo (y no corrige ninguno)."""
        header = manifest.manifest_from_record(_record())
        cases = {
            "project_uid": (
                _record(uid="00000000-0000-4000-8000-0000000000bb"),
                "00000000-0000-4000-8000-0000000000bb",
            ),
            "crs.epsg": (_record(crs_epsg=25829), "25829"),
            "crs.vertical.epsg": (_record(vcrs_epsg=9392), "9392"),
            "geo_origin.x0": (_record(origin_x=736_200), "736200"),
            "geo_origin.z0": (_record(origin_z=-180), "-180"),
        }
        for field, (db_record, shown) in cases.items():
            with self.subTest(campo=field):
                check = manifest.compare(header, db_record)
                self.assertEqual(check.status, manifest.ManifestStatus.INCONSISTENT)
                self.assertIn(field, [item.field for item in check.differences])
                error = check.error("Cantera Prueba")
                self.assertIsInstance(error, errors.ProjectError)
                self.assertEqual(error.code, "core.project_inconsistent")
                self.assertIn(shown, str(error))
                difference = next(item for item in check.differences if item.field == field)
                self.assertIn(difference.header_text, str(error))
                self.assertIn(difference.db_text, str(error))

    def test_rewritable_differences(self) -> None:
        """RF-002-05, RF-002-06: si solo difieren ``modified_at`` o la versión de
        Geoblender, o la BD registra una migración que la cabecera no tiene, la cabecera
        se regenera desde la BD (REWRITE)."""
        header = manifest.manifest_from_record(_record())
        for db_record, migrations in (
            (_record(modified_at="2026-10-06T09:00:00.000Z"), ()),
            (_record(last_written_with="0.2.0"), ()),
            (_record(schema_version=2, min_reader_schema=1), ((1, 2),)),
        ):
            with self.subTest(bd=db_record):
                check = manifest.compare(header, db_record, migrations)
                self.assertEqual(check.status, manifest.ManifestStatus.REWRITE)
                self.assertIsNone(check.error("Cantera Prueba"))

    def test_schema_without_registered_migration(self) -> None:
        """RF-002-05: un esquema distinto que no explica una migración registrada (la
        cabecera por delante de la BD, o la BD por delante sin su fila de
        ``gb_schema_migration``) es INCONSISTENT."""
        newer_header = manifest.manifest_from_record(_record(schema_version=2))
        self.assertEqual(
            manifest.compare(newer_header, _record()).status,
            manifest.ManifestStatus.INCONSISTENT,
        )
        header = manifest.manifest_from_record(_record())
        self.assertEqual(
            manifest.compare(header, _record(schema_version=2)).status,
            manifest.ManifestStatus.INCONSISTENT,
        )

    def test_origin_explained_by_last_move(self) -> None:
        """RF-002-05, RF-002-27: una diferencia de GeoOrigin que explica el último cambio
        de ventana registrado (de = la cabecera, a = la BD) se regenera desde la BD
        (REWRITE), como una migración; si no la explica (otro origen en la cabecera o en
        la BD, o sin cambio registrado), sigue siendo INCONSISTENT (convergencia, T40;
        RF-002-05 de la spec 0.4, enmienda aprobada el 06/10/2026)."""
        header = manifest.manifest_from_record(_record())
        moved = _record(origin_x=701_000, modified_at="2026-10-06T09:00:00.000Z")
        move = ((700_000, 4_400_000, 0), (701_000, 4_400_000, 0))
        check = manifest.compare(header, moved, (), move)
        self.assertEqual(check.status, manifest.ManifestStatus.REWRITE)
        self.assertIn("geo_origin.x0", [item.field for item in check.differences])
        self.assertIsNone(check.error("Cantera Prueba"))
        for db_record, origin_move in (
            (moved, None),
            (moved, ((700_100, 4_400_000, 0), (701_000, 4_400_000, 0))),
            (_record(origin_x=702_000), move),
            (_record(origin_x=701_000, uid="00000000-0000-4000-8000-0000000000bb"), move),
        ):
            with self.subTest(bd=db_record.origin_x, cambio=origin_move):
                check = manifest.compare(header, db_record, (), origin_move)
                self.assertEqual(check.status, manifest.ManifestStatus.INCONSISTENT)

    def test_rewrite_keeps_inventory_and_checkout(self) -> None:
        """RF-002-06: la cabecera regenerada desde la BD toma de ella identidad, CRS,
        origen, versiones y fechas, y conserva lo que la BD no tiene (inventario y
        sección ``checkout``)."""
        previous = manifest.parse_manifest(
            _with(_data(), "checkout", {"session_uid": SESSION_UID, "base": {}, "at": CREATED,
                                        "by": "prueba@PC-PRUEBA-A"})
        )
        db_record = _record(modified_at="2026-10-06T09:00:00.000Z", last_written_with="0.2.0")
        rewritten = manifest.manifest_from_record(db_record, previous=previous)
        self.assertEqual(rewritten.checkout, previous.checkout)
        self.assertEqual(rewritten.inventory, previous.inventory)
        self.assertEqual(rewritten.modified_at, "2026-10-06T09:00:00.000Z")
        self.assertEqual(rewritten.geoblender_version, "0.2.0")
        self.assertEqual(
            manifest.compare(rewritten, db_record).status, manifest.ManifestStatus.CONSISTENT
        )


class AtomicWriteTest(unittest.TestCase):
    def test_interrupted_write_keeps_previous(self) -> None:
        """RF-002-06: una escritura interrumpida (fallo al volcar al disco o al
        sustituir) deja la cabecera anterior intacta, informa y no deja el temporal."""
        for target in ("fsync", "replace"):
            with self.subTest(fallo=target), project_tmp() as tmp:
                old = manifest.manifest_from_record(_record())
                manifest.write_manifest(tmp, old, SESSION_UID)
                before = (tmp / "manifest.json").read_bytes()
                new = manifest.manifest_from_record(_record(modified_at="2026-10-06T09:00:00.000Z"))
                with mock.patch.object(manifest.os, target, side_effect=OSError(5, "E/S")):
                    with self.assertRaises(errors.ProjectError) as caught:
                        manifest.write_manifest(tmp, new, SESSION_UID)
                self.assertEqual(caught.exception.code, "core.manifest_write_failed")
                self.assertEqual((tmp / "manifest.json").read_bytes(), before)
                self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["manifest.json"])

    def test_leftover_temporary_is_ignored(self) -> None:
        """RF-002-06: el temporal a medias de un proceso que murió al escribir no cambia
        lo que se lee, y la siguiente escritura de esa sesión lo sustituye. El temporal es
        ``manifest.json.tmp-`` y 8 cifras hexadecimales de la sesión (T45)."""
        with project_tmp() as tmp:
            header = manifest.manifest_from_record(_record())
            manifest.write_manifest(tmp, header, SESSION_UID)
            leftover = manifest.manifest_temporary_path(tmp, SESSION_UID)
            self.assertRegex(leftover.name, r"^manifest\.json\.tmp-[0-9a-f]{8}$")
            leftover.write_bytes(b'{"format": "geoblender-pro')
            self.assertEqual(manifest.read_manifest(tmp), header)
            manifest.write_manifest(tmp, header, SESSION_UID)
            self.assertFalse(leftover.exists())


class DatabaseRecordTest(unittest.TestCase):
    def test_record_round_trip_in_database(self) -> None:
        """RF-002-05: la fila de ``gb_project`` se escribe y se lee como el mismo
        registro, y las migraciones registradas se leen en orden."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            record = _local_record()
            with gpkg.GpkgConnection.open_write(path, create=True) as db:
                with db.transaction() as conn:
                    base.create_base(conn, CRS)
                    schema.create_schema(conn)
                    schema.insert_project(conn, record)
                    for step in ((1, 2), (2, 3)):
                        conn.execute(
                            "INSERT INTO gb_schema_migration (from_version, to_version, "
                            "applied_at, applied_with, backup_dir, user_host) VALUES "
                            "(?, ?, ?, '0.1.0', 'p.gbproj.respaldo-esquema-1', 'u@h')",
                            (*step, CREATED),
                        )
            with gpkg.GpkgConnection.open_read(path) as db:
                self.assertEqual(schema.read_project(db.connection), record)
                self.assertEqual(schema.read_migrations(db.connection), ((1, 2), (2, 3)))
            empty = tmp / "vacio.gpkg"
            with gpkg.GpkgConnection.open_write(empty, create=True) as db:
                with db.transaction() as conn:
                    base.create_base(conn, CRS)
                    schema.create_schema(conn)
            with gpkg.GpkgConnection.open_read(empty) as db:
                self.assertIsNone(schema.read_project(db.connection))

    def test_record_types(self) -> None:
        """RF-002-05: el registro da el GeoOrigin y la ventana como tipos del dominio, y
        rechaza un GeoOrigin con decimales."""
        record = _record()
        self.assertEqual(record.origin, georef.GeoOrigin(700_000, 4_400_000, 0))
        self.assertEqual(record.window, georef.Window(699_500.0, 4_399_500.0, 700_501.0, 4_400_501.0))
        with self.assertRaises(errors.ValidationError):
            _ = _record(origin_x=700_000.5).origin


if __name__ == "__main__":
    unittest.main()

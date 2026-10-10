# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de las entradas (spec 008, T20 y T21; RF-008-07, RF-008-11, RF-008-12, RF-008-54,
RF-008-55; RF-002-19; ADR-0024 §1, §3 y §6; plan 008 §5.2.1, §5.3.1 y §5.4.8).

``core.inputs`` registra cada fuente que un módulo importa al proyecto:

- ``InputSpec`` la declara: nombre lógico, tipo, módulo, lector, sus ficheros (``SourceFile``:
  dentro del proyecto, una tabla del proyecto, junto al original o con su ruta en los datos de
  usuario del equipo, RF-002-19) con su huella, su tamaño y su fecha (``SourcePrint``), capa,
  CRS horizontal y vertical declarados, ajustes (y cuáles son contenido), hashes con su
  normalizador y su lector, y la entrega;
- ``classify_import`` dice si lo importado es una entrada nueva, la misma que una vigente
  (reutilizarla, con el aviso de la spec §8) o la misma con otros ajustes (sustituirla, con
  motivo) (RF-008-54);
- ``register_input`` la registra con su importación en curso, quién y cuándo, en la transacción
  del módulo y con el evento ``input_registered`` (RF-008-07); sin CRS declarado en un tipo con
  coordenadas, la rechaza;
- ``reuse_input`` deja la importación cancelada con el aviso y el evento ``input_reused``;
- ``locate_source`` y ``resolve_source``: dónde se ancla un fichero y cómo se vuelve a encontrar;
- ``supersede`` (RF-008-11), ``keep_copy`` (RF-008-12), ``discard`` (RF-008-55) y
  ``edit_delivery`` (D-11): sustituir una entrada (la anterior y lo importado quedan como
  historia, con sucesor por papel), mantener la copia de una cambiada, descartarla con motivo y
  cambiar su nombre lógico y su entrega sin cambiar la entrada.

Cada prueba crea su proyecto sintético (esquema 2) con un reloj simulado, copia las fuentes de
``tests/data/core/provenance/`` a una carpeta junto a él y registra el tipo de operación y los
lectores de prueba.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import ntpath
import re
import shutil
import sqlite3
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tests.support import provenance_data as data
from tests.support.core_fixtures import (
    CLOCK_START,
    FakeClock,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered, snapshot
from tests.support.provenance_readers import registered as readers_registered
from tests.support.trees import age_folders

inputs = import_geoblender("core.inputs")
model = import_geoblender("core.inputs.model")
registry = import_geoblender("core.inputs.registry")
create = import_geoblender("core.project.create")
events = import_geoblender("core.project.events")
userdata_mod = import_geoblender("core.userdata")
provenance = import_geoblender("core.provenance")
messages = import_geoblender("core.provenance.messages")
operations = import_geoblender("core.provenance.operations")
schema = import_geoblender("core.provenance.schema")
content = import_geoblender("core.content")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
datasets = import_geoblender("core.datasets")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")
paths = import_geoblender("core.paths")
timeutil = import_geoblender("core.timeutil")

ProvenanceError = messages.ProvenanceError

SESSION = make_session()
NOW = timeutil.format_utc(CLOCK_START)
UNKNOWN_UID = "00000000-0000-4000-8000-0000000002ff"
ETRS89 = {"epsg": 25830}
ED50 = {"epsg": 23030}
REDNAP = {"epsg": 5782}
NOT_APPLICABLE = {"not_applicable": True}
WORKS = {"local": "cota de obra"}
REASON = "La propiedad corrige el CRS: el límite está en ED50"
LAYER = data.LAYER
COLLAR_COLUMNS = {"sondeo": "hole", "este": "x", "norte": "y", "cota": "z", "profundidad": "depth"}
RENAMED_COLUMNS = {"sondeo": "hole", "este": "x", "norte": "y", "z": "z", "profundidad": "depth"}
COLLARS_PATH = "../../fuentes/collares.csv"
MTIME_NS = 1_790_000_000_000_000_000
TABLES = ("gb_input", "gb_input_file", "gb_operation", "gb_operation_io", "gb_dataset",
          "gb_dataset_change", "gb_event")
GPKG = builtin.GPKG_LAYER.id
UPDATE_REASON = "La propiedad entrega la campaña corregida (Q:\\entregas\\carta.pdf)"
UPDATE_REASON_STORED = "La propiedad entrega la campaña corregida (carta.pdf)"
DISCARD_REASON = "Importación equivocada: era la campaña de 2019"
SHARED_TABLE = "res_ensayos"
ACCUMULATED = {"column": "input_uid", "of": "current_inputs"}
ROWS_V1 = (("S-01", 1.5), ("S-02", 2.0))
ROWS_V2 = (("S-01", 1.5), ("S-02", 2.25))
ROWS_B = (("S-03", 0.5),)


def _unread(request: Any) -> Any:
    raise AssertionError("las pruebas del registro no leen con el lector de prueba")


SOURCE = readers.ContentReader("test.source", 1, model.INPUT_KINDS, False, False, None, _unread)
IMPORT = provenance.OperationDef("res.import_source", "1.0", "res", "Test source import", False)


def _sha(label: str) -> str:
    return hashing.sha256_bytes(label.encode("utf-8"))


def _digest(label: str, kind: str, declarations: Mapping[str, Any],
            reader: str = SOURCE.id) -> Any:
    """Los hashes que da el importador de una fuente cuyos datos simula ``label``."""
    data_sha = _sha(label)
    return content.ContentDigest(data_sha, content.content_sha256(kind, declarations, data_sha),
                                 content.NORMALIZER, reader)


def _other_drive(path: Path) -> str:
    """Una unidad que no es la de ``path``: otro volumen simulado."""
    drive = ntpath.splitdrive(str(path))[0].upper()
    return "R:" if drive == "Q:" else "Q:"


def _normalised(path: Path) -> Path:
    """Canonización sin tocar el disco ni la red (para rutas de otras unidades)."""
    return Path(ntpath.normpath(ntpath.abspath(str(path))))


def _same_path(first: Path | None, second: Path) -> bool:
    return first is not None and ntpath.normcase(str(first)) == ntpath.normcase(str(second))


def _check_list(ddl: str, column: str) -> list[str]:
    """Los valores de ``CHECK (<columna> IN (…))`` de una tabla del esquema."""
    found = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", ddl)
    assert found is not None, column
    return [value.strip().strip("'") for value in found.group(1).split(",")]


def _equals(uid: str) -> dict[str, str]:
    return {"column": "input_uid", "equals": uid}


def _imported(name: str, table: str, uid: str, *, shared: bool = False) -> Any:
    """Lo importado de la entrada ``uid``: inmutable; en una tabla común, con su selector."""
    return datasets.DatasetSpec(name, "res", "table", "gpkg", table, reader=GPKG, role="imported",
                                selector=_equals(uid) if shared else None, input_uid=uid,
                                immutable=True)


def _accumulated(table: str) -> Any:
    """El dato acumulado de una tabla común: las filas de las entradas activas."""
    return datasets.DatasetSpec(table, "res", "table", "gpkg", table, reader=GPKG,
                                role="accumulated", selector=ACCUMULATED)


def _write_rows(conn: sqlite3.Connection, table: str, uid: str,
                rows: tuple[tuple[str, float], ...]) -> None:
    """Las filas de lo importado de la entrada ``uid`` en ``table`` (creada si no está)."""
    found = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?", (table,))
    if found.fetchone() is None:
        base.create_attribute_table(conn, table, [base.ColumnDef("input_uid", "TEXT"),
                                                  base.ColumnDef("codigo", "TEXT"),
                                                  base.ColumnDef("ley", "DOUBLE")], table)
    conn.executemany(f'INSERT INTO "{table}" (input_uid, codigo, ley) VALUES (?, ?, ?)',
                     [(uid, code, value) for code, value in rows])


class InputsCase(unittest.TestCase):
    """Un proyecto nuevo por prueba con las fuentes de prueba en ``fuentes/``, junto a él."""

    def setUp(self) -> None:
        before = snapshot()
        self.addCleanup(lambda: self.assertEqual(snapshot(), before))
        self.enterContext(registered(IMPORT))
        self.enterContext(readers_registered(builtin.GPKG_LAYER, builtin.DOCUMENT, SOURCE))
        tmp = self.enterContext(project_tmp("gb-t20-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        self.tmp = tmp
        self.sources = tmp / "fuentes"
        self.sources.mkdir()
        for name in (data.BOUNDARY_V1, data.BOUNDARY_V1_QGIS, data.BOUNDARY_V2, data.REPORT):
            shutil.copyfile(data.DATA_DIR / name, self.sources / name)
        self.clock = FakeClock()
        self.userdata = userdata_mod.UserData(tmp / "u")
        self.project = create.create_project(
            parent, make_settings(), SESSION, self.userdata, clock=self.clock
        ).project
        self.addCleanup(self.project.close)

    # --- Ayudas -----------------------------------------------------------------------------

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.read() as conn:
            return work(conn)

    def rows(self, table: str, where: str = "1", args: tuple[Any, ...] = ()) -> list[dict]:
        """Las filas de ``table`` como diccionarios, por ``fid``."""
        with self.project.read() as conn:
            cursor = conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY fid", args)
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def snapshot(self) -> list[Any]:
        with self.project.read() as conn:
            return [conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in TABLES]

    def logged(self, kind: Any) -> list[Any]:
        return self.read(lambda conn: events.read_events(conn, kind))

    def begin(self) -> Any:
        return operations.begin_operation(self.project, IMPORT.op_type, settings={},
                                          executor="blender")

    def classify(self, spec: Any) -> Any:
        return self.read(lambda conn: registry.classify_import(conn, spec))

    def register(self, spec: Any, **kw: Any) -> Any:
        """Registra ``spec`` con su importación, completada en la misma transacción."""
        handle = self.begin()

        def work(conn: sqlite3.Connection) -> Any:
            record = registry.register_input(conn, self.project, spec,
                                             operation_uid=handle.uid, **kw)
            handle.complete(conn)
            return record

        return self.write(work)

    def refused(self, error: type[BaseException], code: str | None,
                work: Callable[[sqlite3.Connection], Any]) -> BaseException:
        """``work`` se rechaza en una transacción de escritura sin escribir nada y el proyecto
        sigue en escritura."""
        before = self.snapshot()
        with self.assertRaises(error) as caught:
            self.write(work)
        if code is not None:
            self.assertEqual(getattr(caught.exception, "code", None), code,
                             str(caught.exception))
        self.assertTrue(self.project.writable)
        self.assertEqual(self.snapshot(), before)
        return caught.exception

    def rejected(self, error: type[BaseException], code: str | None, spec: Any,
                 **kw: Any) -> BaseException:
        """Registrar ``spec`` con una importación en curso se rechaza sin escribir nada."""
        kw.setdefault("operation_uid", self.begin().uid)
        return self.refused(
            error, code, lambda conn: registry.register_input(conn, self.project, spec, **kw)
        )

    def mark(self, uid: str, status: str, reason: str) -> None:
        """Cambia a mano el estado de una entrada (lo que harán supersede y discard)."""
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = ?, status_at = ?, status_by = ?, status_reason = ?, "
            "modified_at = ? WHERE uid = ?",
            (status, NOW, SESSION.user_host, reason, NOW, uid),
        ))

    def boundary(self, file_name: str = data.BOUNDARY_V1, *, name: str = "Limites_v1",
                 crs_h: Any = ETRS89, crs_v: Any = NOT_APPLICABLE, **changes: Any) -> Any:
        """La capa ``limites`` de una fuente de ``fuentes/``, leída con el lector de
        GeoPackage de core."""
        path = self.sources / file_name
        declarations = model.input_declarations(crs_h, crs_v, {})
        request = builtin.GPKG_LAYER.request("vector", declarations, {"main": path},
                                             {"layer": LAYER})
        stat = path.stat()
        values: dict[str, Any] = {
            "files": [registry.locate_source(path, self.project, self.userdata)],
            "file_prints": [model.SourcePrint(hashing.sha256_file(path), size=stat.st_size,
                                              mtime_ns=stat.st_mtime_ns)],
            "digest": readers.read_content(builtin.GPKG_LAYER, request),
            "crs_h": crs_h,
            "crs_v": crs_v,
            "layer": LAYER,
            "settings": {"layer": LAYER},
            "received_at": "2026-09-24",
            "received_from": "La propiedad",
        }
        values.update(changes)
        return model.InputSpec(name, "vector", "res", builtin.GPKG_LAYER.id, **values)

    def collars(self, columns: Mapping[str, str] = COLLAR_COLUMNS, *,
                conventions: Mapping[str, Any] | None = None,
                extra: Mapping[str, Any] | None = None, crs_h: Any = ETRS89,
                crs_v: Any = REDNAP, name: str = "collares", label: str = "collares",
                **changes: Any) -> Any:
        """Las bocas de sondeos de un CSV junto al proyecto, con hashes simulados por
        ``label``: las mismas filas leídas con las columnas ``columns``; ``conventions`` son
        los ajustes que son contenido (por defecto, las unidades) y ``extra``, otros."""
        chosen = {"units": "m"} if conventions is None else dict(conventions)
        settings = {"columns": dict(columns), "separator": ";", **(extra or {}), **chosen}
        declarations = model.input_declarations(crs_h, crs_v, chosen)
        values: dict[str, Any] = {
            "files": [model.SourceFile(COLLARS_PATH, "main", "original")],
            "file_prints": [model.SourcePrint(_sha(f"{label}:{sorted(columns)}"), size=626,
                                              mtime_ns=MTIME_NS)],
            "digest": _digest(label, "table", declarations),
            "crs_h": crs_h,
            "crs_v": crs_v,
            "settings": settings,
            "content_settings_keys": tuple(chosen),
        }
        values.update(changes)
        return model.InputSpec(name, "table", "res", SOURCE.id, **values)

    def simple(self, name: str, kind: str, crs_h: Any, crs_v: Any) -> Any:
        """Una fuente de un fichero junto al proyecto, del tipo ``kind``, con hashes
        simulados."""
        return model.InputSpec(
            name, kind, "res", SOURCE.id,
            files=[model.SourceFile(f"../../fuentes/{name}.bin", "main", "original")],
            file_prints=[model.SourcePrint(_sha(name), size=10, mtime_ns=MTIME_NS)],
            digest=_digest(name, kind, model.input_declarations(crs_h, crs_v, {})),
            crs_h=crs_h, crs_v=crs_v,
        )


class RegisterTest(InputsCase):
    def test_registers_input_with_its_files_and_import(self) -> None:
        """RF-008-07: la entrada «Limites_v1» queda con su nombre lógico, tipo, módulo, lector y
        normalizador, capa, CRS horizontal y vertical declarados, ajustes (JSON canónico y su
        huella, CRS incluidos), la huella conjunta de sus bytes, los hashes de datos y de
        contenido, la entrega, quién la registra y cuándo, su importación (en curso, completada
        en la misma transacción) y su estado; su fichero, anclado junto al proyecto (RF-002-19)
        con su tamaño, su fecha y su huella; el evento ``input_registered``, sin rutas
        absolutas. Registrarla no toca la carpeta de la fuente, y lo guardado basta para volver
        a calcular su hash de contenido y para encontrar el fichero."""
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            spec = self.boundary()
            record = self.register(spec)
        path = self.sources / data.BOUNDARY_V1
        stat = path.stat()
        file_sha = hashing.sha256_file(path)
        (operation,) = self.rows("gb_operation")
        self.assertEqual((operation["op_type"], operation["status"]), (IMPORT.op_type, "done"))
        settings_identity = {"content_keys": [], "crs_h": ETRS89, "crs_v": NOT_APPLICABLE,
                             "layer": LAYER, "values": {"layer": LAYER}}
        self.assertEqual(self.rows("gb_input"), [{
            "fid": 1,
            "uid": record.uid,
            "name": "Limites_v1",
            "kind": "vector",
            "module": "res",
            "reader": "core.gpkg_layer@1",
            "normalizer": "gbch/1",
            "layer": "limites",
            "crs_h": '{"epsg":25830}',
            "crs_v": '{"not_applicable":true}',
            "settings": '{"content_keys":[],"values":{"layer":"limites"}}',
            "settings_sha256": hashing.sha256_bytes(hashing.canonical_json(settings_identity)),
            "bytes_sha256": hashing.sha256_bytes(hashing.canonical_json([file_sha])),
            "data_sha256": spec.digest.data_sha256,
            "content_sha256": spec.digest.content_sha256,
            "received_at": "2026-09-24",
            "received_from": "La propiedad",
            "registered_by": "prueba@PC-PRUEBA-A",
            "registered_at": NOW,
            "operation_uid": operation["uid"],
            "previous_uid": None,
            "status": "current",
            "status_at": None,
            "status_by": None,
            "status_reason": None,
            "seen_sha256": None,
            "original": "not_applicable",
            "created_at": NOW,
            "modified_at": NOW,
        }])
        unchecked = dict.fromkeys(
            ("checked_size", "checked_mtime_ns", "checked_last_change", "checked_at",
             "original_path", "original_sha256", "original_size", "original_mtime_ns")
        )
        self.assertEqual(self.rows("gb_input_file"), [{
            "fid": 1,
            "input_uid": record.uid,
            "ord": 0,
            "role": "main",
            "anchor": "original",
            "path": "../../fuentes/Limites_v1.gpkg",
            "ref_uid": None,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "last_change": None,
            "sha256": file_sha,
            **unchecked,
        }])
        # El registro leído, por uid o por nombre, con sus declaraciones y su hash.
        self.assertEqual(self.read(lambda conn: registry.get(conn, record.uid)), record)
        self.assertEqual(self.read(lambda conn: registry.get(conn, "Limites_v1")), record)
        self.assertIsNone(self.read(lambda conn: registry.get(conn, "Limites_v9")))
        self.assertEqual(record.declarations,
                         {"conventions": {}, "crs_h": ETRS89, "crs_v": NOT_APPLICABLE})
        self.assertEqual(
            content.content_sha256("vector", record.declarations, record.data_sha256),
            record.content_sha256,
        )
        self.assertEqual(record.digest, spec.digest)
        self.assertEqual((record.settings, record.content_settings_keys), ({"layer": LAYER}, ()))
        self.assertEqual((record.status, record.active), (model.InputStatus.CURRENT, True))
        self.assertEqual(record.original, model.OriginalState.NOT_APPLICABLE)
        (source,) = record.files
        self.assertEqual((source.anchor, source.role), (model.FileAnchor.ORIGINAL,
                                                        model.FileRole.MAIN))
        found = registry.resolve_source(source, self.project, self.userdata)
        self.assertTrue(_same_path(found, path.resolve()), found)
        # El evento, sin rutas absolutas.
        (event,) = self.logged(events.EventKind.INPUT_REGISTERED)
        self.assertEqual(
            (event.user_host, event.session_uid, event.at, event.entity_kind, event.entity_uid),
            (SESSION.user_host, SESSION.session_uid, NOW, "input", record.uid),
        )
        self.assertEqual(event.message, "Entrada «Limites_v1» registrada (vector, "
                                        "core.gpkg_layer@1).")
        self.assertEqual(event.data, {
            "name": "Limites_v1",
            "kind": "vector",
            "module": "res",
            "reader": "core.gpkg_layer@1",
            "normalizer": "gbch/1",
            "layer": "limites",
            "crs_h": ETRS89,
            "crs_v": NOT_APPLICABLE,
            "data_sha256": spec.digest.data_sha256,
            "content_sha256": spec.digest.content_sha256,
            "operation_uid": operation["uid"],
            "previous_uid": None,
            "reason": None,
            "received_at": "2026-09-24",
            "received_from": "La propiedad",
            "files": [{"anchor": "original", "path": "../../fuentes/Limites_v1.gpkg",
                       "role": "main"}],
        })
        stored = [self.rows(table) for table in ("gb_input", "gb_input_file")]
        shown = [[item.message, item.data] for item in self.logged(None)]
        self.assertEqual(paths.find_absolute_paths([stored, shown]), [])

    def test_files_anchored_in_project_table_original_or_userdata(self) -> None:
        """RF-008-07, RF-002-19: un fichero dentro del proyecto se guarda relativo a él (con su
        compañero ``.prj``); uno del mismo volumen, relativo al original; uno de otro volumen,
        solo su nombre, con su ruta anotada en los datos de usuario del equipo (en otro equipo,
        «no localizable»); una capa creada en el proyecto, como tabla del proyecto, con el
        ``last_change`` que tiene al registrarla y sin tamaño ni fecha. Cada uno se vuelve a
        encontrar, nada guarda una ruta absoluta y los ficheros no se tocan."""
        inside = self.project.root / "fuentes"
        inside.mkdir()
        (inside / "mdt.asc").write_bytes(b"ncols 2\nnrows 1\n1 2\n")
        (inside / "mdt.prj").write_bytes(b'PROJCS["ETRS89 / UTM zone 30N"]')
        age_folders(inside)
        with assert_source_untouched(inside):
            grid_files = [
                registry.locate_source(inside / "mdt.asc", self.project, self.userdata),
                registry.locate_source(inside / "mdt.prj", self.project, self.userdata,
                                       role="sidecar"),
            ]
            self.assertEqual(grid_files, [
                model.SourceFile("fuentes/mdt.asc", "main", "project"),
                model.SourceFile("fuentes/mdt.prj", "sidecar", "project"),
            ])
            grid = model.InputSpec(
                "MDT_obra", "raster", "res", SOURCE.id, files=grid_files,
                file_prints=[
                    model.SourcePrint(hashing.sha256_file(inside / name),
                                      size=(inside / name).stat().st_size,
                                      mtime_ns=(inside / name).stat().st_mtime_ns)
                    for name in ("mdt.asc", "mdt.prj")
                ],
                digest=_digest("mdt", "raster", model.input_declarations(ETRS89, REDNAP, {})),
                crs_h=ETRS89, crs_v=REDNAP,
            )
            grid_record = self.register(grid)
        self.assertEqual(grid_record.bytes_sha256, hashing.sha256_bytes(hashing.canonical_json(
            [hashing.sha256_file(inside / "mdt.asc"), hashing.sha256_file(inside / "mdt.prj")]
        )))
        # Otro volumen: solo el nombre en el proyecto y la ruta en los datos de usuario.
        remote = Path(f"{_other_drive(self.project.root)}/entregas/informe.pdf")
        remote_file = registry.locate_source(remote, self.project, self.userdata,
                                             canonical=_normalised)
        self.assertEqual((remote_file.path, remote_file.role, remote_file.anchor),
                         ("informe.pdf", "main", "external"))
        self.assertTrue(remote_file.ref_uid)
        pdf = self.sources / data.REPORT
        no_crs = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        report = model.InputSpec(
            "Informe_propiedad", "document", "res", builtin.DOCUMENT.id, files=[remote_file],
            file_prints=[model.SourcePrint(hashing.sha256_file(pdf), size=pdf.stat().st_size,
                                           mtime_ns=pdf.stat().st_mtime_ns)],
            digest=readers.read_content(
                builtin.DOCUMENT, builtin.DOCUMENT.request("document", no_crs, {"main": pdf})
            ),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )
        report_record = self.register(report)
        # Una capa creada en el proyecto (desde QGIS): su tabla.

        def make_layer(conn: sqlite3.Connection) -> None:
            base.create_attribute_table(conn, "res_capa_qgis",
                                        [base.ColumnDef("valor", "DOUBLE")], "Capa de QGIS")
            conn.execute('INSERT INTO "res_capa_qgis" (valor) VALUES (1.5)')

        self.write(make_layer)
        last_change = self.read(lambda conn: conn.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name = 'res_capa_qgis'"
        ).fetchone()[0])
        self.assertTrue(last_change)
        table = model.InputSpec(
            "Capa_QGIS", "table", "res", SOURCE.id,
            files=[model.SourceFile("res_capa_qgis", "main", "project_table")],
            file_prints=[model.SourcePrint(_sha("capa"))],
            digest=_digest("capa", "table", no_crs), crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )
        table_record = self.register(table)
        stored = {
            row["path"]: (row["input_uid"], row["ord"], row["role"], row["anchor"],
                          row["ref_uid"], row["size"] is None, row["last_change"])
            for row in self.rows("gb_input_file")
        }
        self.assertEqual(stored, {
            "fuentes/mdt.asc": (grid_record.uid, 0, "main", "project", None, False, None),
            "fuentes/mdt.prj": (grid_record.uid, 1, "sidecar", "project", None, False, None),
            "informe.pdf": (report_record.uid, 0, "main", "external", remote_file.ref_uid,
                            False, None),
            "res_capa_qgis": (table_record.uid, 0, "main", "project_table", None, True,
                              last_change),
        })
        (table_file,) = table_record.files
        self.assertEqual((table_file.size, table_file.mtime_ns, table_file.sha256),
                         (None, None, _sha("capa")))
        # Cada fichero se vuelve a encontrar (el de otro volumen, solo en este equipo).
        for source, expected in zip(grid_record.files, ("mdt.asc", "mdt.prj"), strict=True):
            found = registry.resolve_source(source, self.project, self.userdata)
            self.assertTrue(_same_path(found, (inside / expected).resolve()), found)
        (report_file,) = report_record.files
        self.assertEqual(registry.resolve_source(report_file, self.project, self.userdata,
                                                 canonical=_normalised), _normalised(remote))
        elsewhere = userdata_mod.UserData(self.tmp / "otro-equipo")
        self.assertIsNone(registry.resolve_source(report_file, self.project, elsewhere,
                                                  canonical=_normalised))
        with self.assertRaises(ValueError):
            registry.resolve_source(table_file, self.project, self.userdata)
        refs = self.userdata.external_refs(self.project.uid)
        self.assertEqual(refs, {remote_file.ref_uid: str(_normalised(remote))})
        stored_rows = [self.rows(name) for name in ("gb_input", "gb_input_file")]
        shown = [[item.message, item.data] for item in self.logged(None)]
        self.assertEqual(paths.find_absolute_paths([stored_rows, shown]), [])

    def test_project_table_must_exist(self) -> None:
        """RF-008-07: una entrada anclada a una tabla del proyecto que no está en
        ``gpkg_contents`` se rechaza sin escribir nada."""
        no_crs = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        spec = model.InputSpec(
            "Capa_QGIS", "table", "res", SOURCE.id,
            files=[model.SourceFile("res_capa_qgis", "main", "project_table")],
            file_prints=[model.SourcePrint(_sha("capa"))],
            digest=_digest("capa", "table", no_crs), crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )
        error = self.rejected(ProvenanceError, "core.input_table_missing", spec)
        self.assertEqual(str(error), "La tabla «res_capa_qgis» de la entrada «Capa_QGIS» no es "
                                     "una capa ni una tabla del proyecto.")

    def test_crs_declared_never_assumed(self) -> None:
        """RF-008-07 (constitución, principio 6): una entrada sin CRS horizontal o vertical
        declarado, o con «no aplica» donde hay coordenadas (la horizontal de una capa, la
        vertical de una malla), se rechaza al clasificarla y al registrarla, sin escribir nada;
        un documento o una tabla sin coordenadas declaran «no aplica» en las dos, y una capa
        plana, en la vertical."""
        cases = (
            ("horizontal", "core.input_crs_missing", self.boundary(crs_h=None)),
            ("vertical", "core.input_crs_missing", self.boundary(crs_v=None)),
            ("horizontal", "core.input_crs_not_applicable",
             self.boundary(crs_h=NOT_APPLICABLE)),
            ("vertical", "core.input_crs_missing", self.collars(crs_v=None)),
            ("vertical", "core.input_crs_not_applicable",
             self.simple("Corta", "mesh", ETRS89, NOT_APPLICABLE)),
            ("horizontal", "core.input_crs_not_applicable",
             self.simple("Nube", "point_cloud", NOT_APPLICABLE, REDNAP)),
            ("horizontal", "core.input_crs_missing",
             self.simple("Informe", "document", None, NOT_APPLICABLE)),
        )
        for axis, code, spec in cases:
            with self.subTest(name=spec.name, axis=axis, code=code):
                with self.assertRaises(ProvenanceError) as caught:
                    self.classify(spec)
                self.assertEqual((caught.exception.code, caught.exception.values["axis"]),
                                 (code, axis))
                self.rejected(ProvenanceError, code, spec)
        self.assertEqual(
            str(self.rejected(ProvenanceError, None, cases[0][2])),
            "La entrada «Limites_v1» (vector) no declara su CRS horizontal: declárelo al "
            "importar; Geoblender nunca lo supone.",
        )
        self.assertEqual(
            str(self.rejected(ProvenanceError, None, cases[4][2])),
            "La entrada «Corta» es de tipo «mesh», con coordenadas: su CRS vertical no puede "
            "ser «no aplica».",
        )
        for spec in (self.collars(crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE),
                     self.simple("Informe", "document", NOT_APPLICABLE, NOT_APPLICABLE),
                     self.simple("MDT", "raster", ETRS89, WORKS),
                     self.simple("Orto", "raster", {"wkt2": 'PROJCRS["Rejilla de mina"]'},
                                 NOT_APPLICABLE),
                     self.simple("Nube", "point_cloud", ETRS89, {"ellipsoidal": 4937})):
            with self.subTest(admitted=spec.name):
                self.assertEqual(self.classify(spec), registry.New())
        record = self.register(self.boundary())
        self.assertEqual((record.crs_h, record.crs_v), (ETRS89, NOT_APPLICABLE))

    def test_import_operation_running(self) -> None:
        """RF-008-07: una entrada se registra con su importación en curso; sin ella, con una
        que no existe o con una ya terminada se rechaza sin escribir nada, y fuera de una
        transacción de escritura es un error del programa."""
        done = self.register(self.boundary(data.BOUNDARY_V2, name="Limites_v2")).operation_uid
        spec = self.boundary()
        for operation_uid, code in ((None, "core.input_operation_missing"),
                                    (UNKNOWN_UID, "core.input_operation_unknown"),
                                    (done, "core.input_operation_not_running")):
            with self.subTest(code=code):
                self.rejected(ProvenanceError, code, spec, operation_uid=operation_uid)
        self.assertEqual(
            str(self.rejected(ProvenanceError, None, spec, operation_uid=done)),
            f"La operación de importación «res.import_source» de la entrada «Limites_v1» "
            f"({done}) ya no está en curso: la entrada se registra antes de completarla.",
        )
        handle = self.begin()
        with self.assertRaises(ValueError):
            self.read(lambda conn: registry.register_input(conn, self.project, spec,
                                                           operation_uid=handle.uid))
        self.assertEqual(self.rows("gb_input", "name = ?", ("Limites_v1",)), [])

    def test_reader_registered_with_its_kind(self) -> None:
        """RF-008-07 (ADR-0024 §6): la entrada queda con su lector para siempre, así que tiene
        que estar registrado (si no, ``core.reader_unregistered``) y dar su tipo de dato (si
        no, error del programa); en los dos casos, sin escribir nada."""
        other = dataclasses.replace(
            self.collars(), reader="test.other@1",
            digest=dataclasses.replace(self.collars().digest, reader="test.other@1"),
        )
        self.rejected(errors.ValidationError, "core.reader_unregistered", other)
        no_crs = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        wrong = model.InputSpec(
            "Informe", "table", "res", builtin.DOCUMENT.id,
            files=[model.SourceFile("../../fuentes/informe.pdf", "main", "original")],
            file_prints=[model.SourcePrint(_sha("pdf"), size=329, mtime_ns=MTIME_NS)],
            digest=_digest("pdf", "table", no_crs, builtin.DOCUMENT.id),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )
        self.rejected(ValueError, None, wrong)


class ClassifyTest(InputsCase):
    def test_same_content_and_settings_reuses_input(self) -> None:
        """RF-008-54: importar otra vez el mismo contenido con los mismos ajustes —también
        reescrito por QGIS (otra huella), con otro nombre o entregado otro día— no duplica la
        entrada: se reutiliza, con el aviso de la spec §8; registrarla otra vez se rechaza con
        ese aviso sin escribir nada, y ``reuse_input`` deja la importación cancelada con él y
        el evento ``input_reused``."""
        v1 = self.register(self.boundary())
        text = "La entrada «Limites_v1» ya está registrada con el mismo contenido (05/10/2026)."
        same = (
            self.boundary(),
            self.boundary(data.BOUNDARY_V1_QGIS, name="Limites_v1_qgis"),
            self.boundary(received_at=dt.date(2026, 10, 1), received_from="Topografía"),
        )
        self.assertNotEqual(same[1].bytes_sha256, v1.bytes_sha256)
        for spec in same:
            with self.subTest(name=spec.name, received=spec.received_at):
                found = self.classify(spec)
                self.assertEqual(found, registry.Reuse(v1))
                self.assertEqual(found.text, text)
                error = self.rejected(ProvenanceError, "core.input_reused", spec)
                self.assertEqual(str(error), text)
        self.assertEqual(
            found.render("en"),
            "Input «Limites_v1» is already registered with the same content (05/10/2026).",
        )
        handle = self.begin()
        registry.reuse_input(self.project, handle, found)
        (operation,) = self.rows("gb_operation", "uid = ?", (handle.uid,))
        self.assertEqual((operation["status"], operation["status_reason"]), ("cancelled", text))
        (event,) = self.logged(events.EventKind.INPUT_REUSED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.message),
                         ("input", v1.uid, text))
        self.assertEqual(event.data, {"name": "Limites_v1", "operation_uid": handle.uid,
                                      "op_type": IMPORT.op_type,
                                      "content_sha256": v1.content_sha256})
        self.assertEqual([row["uid"] for row in self.rows("gb_input")], [v1.uid])
        with self.assertRaises(TypeError):
            registry.reuse_input(self.project, handle, registry.New())

    def test_other_crs_is_a_substitution_with_reason(self) -> None:
        """RF-008-54, RF-008-11: el mismo contenido con otro CRS declarado (ED50 en vez de
        ETRS89) es la sustitución de la entrada vigente, con la diferencia y motivo
        obligatorio: sin nombrar la sustituida, sin motivo o con su nombre aún ocupado se
        rechaza sin escribir nada; ya sustituida, la nueva queda con ``previous_uid`` y el
        motivo (sin rutas absolutas) en su evento, y lo mismo otra vez es reutilizarla."""
        v1 = self.register(self.boundary())
        ed50 = self.boundary(crs_h=ED50)
        self.assertEqual(ed50.digest.data_sha256, v1.data_sha256)
        self.assertNotEqual(ed50.digest.content_sha256, v1.content_sha256)
        found = self.classify(ed50)
        self.assertEqual(found, registry.Substitute(
            v1, (registry.Difference("crs_h", ETRS89, ED50),)
        ))
        self.assertEqual(found.describe(), "CRS horizontal declarado: EPSG:25830 → EPSG:23030")
        self.assertEqual(found.describe("en"),
                         "declared horizontal CRS: EPSG:25830 → EPSG:23030")
        error = self.rejected(ProvenanceError, "core.input_substitution_required", ed50)
        self.assertEqual(
            str(error),
            "La entrada «Limites_v1» tiene el mismo contenido que «Limites_v1» con otros ajustes "
            "de importación (CRS horizontal declarado: EPSG:25830 → EPSG:23030): la importación "
            "la sustituye, con un motivo.",
        )
        for reason in (None, "   "):
            with self.subTest(reason=reason):
                error = self.rejected(ProvenanceError, "core.input_reason_missing", ed50,
                                      previous_uid=v1.uid, reason=reason)
        self.assertEqual(str(error), "Indique el motivo de la sustitución de la entrada "
                                     "«Limites_v1» por «Limites_v1».")
        error = self.rejected(ProvenanceError, "core.input_name_taken", ed50,
                              previous_uid=v1.uid, reason=REASON)
        self.assertEqual(str(error), "Ya hay otra entrada «Limites_v1» en el proyecto: elija "
                                     "otro nombre o actualice esa entrada.")
        self.mark(v1.uid, "superseded", REASON)
        new = self.register(ed50, previous_uid=v1.uid,
                            reason=f"  {REASON} (Q:\\entregas\\carta.pdf)  ")
        self.assertEqual((new.name, new.previous_uid, new.crs_h, new.status),
                         ("Limites_v1", v1.uid, ED50, model.InputStatus.CURRENT))
        (_first, event) = self.logged(events.EventKind.INPUT_REGISTERED)
        self.assertEqual((event.entity_uid, event.data["previous_uid"], event.data["reason"]),
                         (new.uid, v1.uid, f"{REASON} (carta.pdf)"))
        self.assertEqual(event.message, f"Entrada «Limites_v1» registrada: sustituye a "
                                        f"«Limites_v1» ({REASON} (carta.pdf)).")
        self.assertEqual(self.classify(ed50), registry.Reuse(new))
        # Otra sustitución de la vigente tiene que nombrarla a ella, no a otra entrada.
        collars = self.register(self.collars())
        etrs = self.boundary(crs_h={"epsg": 4258}, name="Limites_v1_etrs")
        self.assertEqual(self.classify(etrs), registry.Substitute(
            new, (registry.Difference("crs_h", ED50, {"epsg": 4258}),)
        ))
        self.rejected(ProvenanceError, "core.input_substitution_required", etrs,
                      previous_uid=collars.uid, reason=REASON)
        shown = [[item.message, item.data] for item in self.logged(None)]
        self.assertEqual(paths.find_absolute_paths(shown), [])

    def test_other_columns_or_conventions_is_a_substitution(self) -> None:
        """RF-008-54: las mismas filas leídas con otras columnas (la cota renombrada a «z»),
        con otra convención declarada, otro CRS vertical, otra capa u otros ajustes que son
        contenido son otra importación de la misma entrada: sustitución, con cada
        diferencia; con los mismos ajustes en otro orden, reutilización. Lo que es contenido
        entra en las declaraciones de su hash."""
        v1 = self.register(self.collars())
        self.assertEqual(v1.declarations, {"conventions": {"units": "m"}, "crs_h": ETRS89,
                                           "crs_v": REDNAP})
        self.assertEqual(v1.content_settings_keys, ("units",))
        cases = (
            (self.collars(RENAMED_COLUMNS),
             registry.Difference("settings.columns", COLLAR_COLUMNS, RENAMED_COLUMNS)),
            (self.collars(conventions={"units": "ft"}),
             registry.Difference("settings.units", "m", "ft")),
            (self.collars(crs_v=WORKS), registry.Difference("crs_v", REDNAP, WORKS)),
            (self.collars(layer="Hoja1"), registry.Difference("layer", None, "Hoja1")),
            (self.collars(conventions={}, extra={"units": "m"}),
             registry.Difference("content_keys", ["units"], [])),
            (self.collars(extra={"encoding": "utf-8"}),
             registry.Difference("settings.encoding", None, "utf-8")),
            (self.collars(extra={"comment": None}),
             registry.Difference("settings.comment", None, None)),
        )
        for spec, difference in cases:
            with self.subTest(item=difference.item):
                self.assertEqual(spec.digest.data_sha256, v1.data_sha256)
                self.assertEqual(self.classify(spec), registry.Substitute(v1, (difference,)))
                self.rejected(ProvenanceError, "core.input_substitution_required", spec)
        # Los ajustes se comparan exactos: 1 no es 1.0 ni «sí».
        other = self.register(self.collars(name="collares_b", label="collares-b",
                                           extra={"header": 1}))
        for value in (1.0, True):
            with self.subTest(header=value):
                spec = self.collars(name="collares_b", label="collares-b",
                                    extra={"header": value})
                self.assertEqual(self.classify(spec), registry.Substitute(
                    other, (registry.Difference("settings.header", 1, value),)
                ))
        self.assertEqual(
            registry.Substitute(v1, (cases[1][1], cases[2][1], cases[3][1])).describe(),
            "ajuste «units»: m → ft; CRS vertical declarado: EPSG:5782 → local «cota de obra»; "
            "capa: — → Hoja1",
        )
        reordered = self.collars(dict(reversed(list(COLLAR_COLUMNS.items()))))
        self.assertEqual(self.classify(reordered), registry.Reuse(v1))

    def test_new_content_is_a_new_input(self) -> None:
        """RF-008-54, RF-008-07: otro contenido (el límite redibujado de Limites_v2) es una
        entrada nueva, junto a la vigente; con el nombre lógico de otra entrada activa se
        rechaza sin escribir nada."""
        self.register(self.boundary())
        v2 = self.boundary(data.BOUNDARY_V2, name="Limites_v2")
        self.assertEqual(self.classify(v2), registry.New())
        self.register(v2)
        self.assertEqual([(row["name"], row["status"]) for row in self.rows("gb_input")],
                         [("Limites_v1", "current"), ("Limites_v2", "current")])
        self.rejected(ProvenanceError, "core.input_name_taken", self.collars(name="Limites_v1"))

    def test_previous_input_checked(self) -> None:
        """RF-008-11: la entrada sustituida tiene que existir y no estar descartada ni ya
        sustituida por otra; el motivo solo acompaña a una sustitución. Sin escribir nada."""
        v1 = self.register(self.boundary())
        v2 = self.boundary(data.BOUNDARY_V2, name="Limites_v2")
        error = self.rejected(ProvenanceError, "core.input_previous_unknown", v2,
                              previous_uid=UNKNOWN_UID, reason=REASON)
        self.assertEqual(str(error), f"La entrada a la que sustituye «Limites_v2» "
                                     f"({UNKNOWN_UID}) no está en el proyecto.")
        self.rejected(ValueError, None, v2, reason=REASON)
        self.rejected(TypeError, None, v2, previous_uid=1, reason=REASON)
        self.mark(v1.uid, "discarded", "importación equivocada")
        error = self.rejected(ProvenanceError, "core.input_previous_discarded", v2,
                              previous_uid=v1.uid, reason=REASON)
        self.assertEqual(str(error), "La entrada «Limites_v1» está descartada: queda como "
                                     "registro y no se actualiza.")
        c1 = self.register(self.collars())
        self.mark(c1.uid, "superseded", REASON)
        # Una entrada descartada o sustituida queda como historia: no se reutiliza.
        for spec in (self.boundary(), self.collars()):
            with self.subTest(inactive=spec.name):
                self.assertEqual(self.classify(spec), registry.New())
        self.register(self.collars(label="collares-v2"), previous_uid=c1.uid, reason=REASON)
        error = self.rejected(ProvenanceError, "core.input_previous_replaced",
                              self.collars(label="collares-v3"), previous_uid=c1.uid,
                              reason=REASON)
        self.assertEqual(str(error), "La entrada «collares» ya está sustituida por «collares»: "
                                     "«collares» no la vuelve a sustituir.")


class LifecycleCase(InputsCase):
    """Entradas importadas con lo que escribe su importación (una tabla de ``project.gpkg``)."""

    def load(self, spec: Any, rows: tuple[tuple[str, float], ...], *, table: str,
             dataset: str, shared: bool = False, previous: str | None = None,
             reason: str | None = None, supersedes: str | None = None) -> tuple[Any, Any]:
        """Importa ``spec`` como lo hace un módulo: su importación en curso y, en una sola
        transacción, la sustitución de ``previous`` (si la hay), la entrada, sus filas en
        ``table`` y la importación completada con lo importado (``dataset``) y, en una tabla
        común, el dato acumulado. Devuelve la entrada y la importación."""
        handle = operations.begin_operation(self.project, IMPORT.op_type, settings={},
                                            executor="blender", supersedes=supersedes)

        def work(conn: sqlite3.Connection) -> Any:
            if previous is not None:
                registry.supersede(conn, self.project, previous, operation_uid=handle.uid,
                                   reason=reason)
            record = registry.register_input(conn, self.project, spec, operation_uid=handle.uid,
                                             previous_uid=previous, reason=reason)
            _write_rows(conn, table, record.uid, rows)
            outputs = [_imported(dataset, table, record.uid, shared=shared)]
            if shared:
                outputs.append(_accumulated(table))
            handle.complete(conn, outputs=outputs)
            return record

        return self.write(work), handle

    def later(self) -> str:
        """Avanza el reloj cinco minutos y devuelve la hora nueva, como se guarda."""
        self.clock.advance(minutes=5)
        return timeutil.format_utc(self.clock.now())

    def table(self, table: str, where: str = "1", args: tuple[Any, ...] = ()) -> list[Any]:
        with self.project.read() as conn:
            return conn.execute(f'SELECT * FROM "{table}" WHERE {where} ORDER BY fid',
                                args).fetchall()

    def dataset(self, key: str) -> Any:
        return self.read(lambda conn: datasets.get(conn, key))

    def successor(self, uid: str) -> Any:
        found = self.read(lambda conn: datasets.successor(conn, uid))
        return None if found is None else found.uid

    def foreign_update(self, table: str, uid: str) -> str:
        """Una conexión ajena (QGIS) intenta cambiar las filas de ``uid``: el texto del
        rechazo."""
        conn = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                               isolation_level=None)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            conn.execute(f'UPDATE "{table}" SET ley = 0 WHERE input_uid = ?', (uid,))
        return str(caught.exception)

    def detect(self, uid: str, seen: str) -> None:
        """La comprobación de las fuentes la encuentra cambiada (lo hará ``check_steps``)."""
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'changed', seen_sha256 = ?, modified_at = ? "
            "WHERE uid = ?", (seen, NOW, uid),
        ))

    def supersede(self, uid: str, operation_uid: str, reason: Any = REASON) -> Any:
        return lambda conn: registry.supersede(conn, self.project, uid,
                                               operation_uid=operation_uid, reason=reason)


class SupersedeTest(LifecycleCase):
    def test_update_twice_keeps_every_copy_as_history(self) -> None:
        """RF-008-11, RF-008-52 (spec §8, «Actualizar dos veces una entrada»): sustituir una
        entrada la deja «sustituida» con quién, cuándo y el motivo (sin rutas absolutas), y lo
        demás de ella y de sus ficheros igual; su importación queda con ``superseded_by`` (la
        reimportación que la sustituye lo declare o no al empezar), lo importado queda
        «sustituido» con su nombre, su contenido y sus filas protegidas, y su sucesor se
        resuelve por papel; con el evento ``input_updated``. Tras actualizar dos veces, las
        tres copias de lo importado siguen en el proyecto y lo primero lleva a lo último."""
        v1, op1 = self.load(self.collars(), ROWS_V1, table="res_collares_1",
                            dataset="res_collares")
        input_1 = self.rows("gb_input", "uid = ?", (v1.uid,))[0]
        files_1 = self.rows("gb_input_file", "input_uid = ?", (v1.uid,))
        operation_1 = self.rows("gb_operation", "uid = ?", (op1.uid,))[0]
        data_1 = self.rows("gb_dataset", "input_uid = ?", (v1.uid,))[0]
        changes_1 = self.rows("gb_dataset_change", "dataset_uid = ?", (data_1["uid"],))
        rows_1 = self.table("res_collares_1")
        moment = self.later()
        v2, op2 = self.load(self.collars(label="collares-v2"), ROWS_V2, table="res_collares_2",
                            dataset="res_collares", previous=v1.uid, reason=UPDATE_REASON,
                            supersedes=op1.uid)
        self.assertEqual(self.rows("gb_input", "uid = ?", (v1.uid,)), [{
            **input_1, "status": "superseded", "status_at": moment,
            "status_by": SESSION.user_host, "status_reason": UPDATE_REASON_STORED,
            "modified_at": moment,
        }])
        self.assertEqual(self.rows("gb_input_file", "input_uid = ?", (v1.uid,)), files_1)
        self.assertEqual(self.rows("gb_operation", "uid = ?", (op1.uid,)),
                         [{**operation_1, "superseded_by": op2.uid}])
        self.assertEqual(self.rows("gb_dataset", "uid = ?", (data_1["uid"],)), [{
            **data_1, "status": "superseded", "modified_at": moment,
        }])
        self.assertEqual(self.rows("gb_dataset_change", "dataset_uid = ?", (data_1["uid"],)),
                         changes_1)
        self.assertEqual(self.table("res_collares_1"), rows_1)
        self.assertIn("«collares»", self.foreign_update("res_collares_1", v1.uid))
        self.assertEqual((v2.name, v2.previous_uid, v2.status),
                         ("collares", v1.uid, model.InputStatus.CURRENT))
        data_2 = self.dataset("res_collares")
        self.assertEqual((data_2.input_uid, data_2.operation_uid), (v2.uid, op2.uid))
        self.assertEqual(self.successor(data_1["uid"]), data_2.uid)
        (event,) = self.logged(events.EventKind.INPUT_UPDATED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.user_host),
                         ("input", v1.uid, moment, SESSION.user_host))
        self.assertEqual(event.message,
                         f"Entrada «collares» sustituida ({UPDATE_REASON_STORED}).")
        self.assertEqual(event.data, {
            "name": "collares",
            "from_status": "current",
            "reason": UPDATE_REASON_STORED,
            "operation_uid": op2.uid,
            "op_type": IMPORT.op_type,
            "previous_operation_uid": op1.uid,
            "datasets": [data_1["uid"]],
        })
        # Otra vez: los mismos datos con otro CRS vertical (sustitución de RF-008-54), con una
        # importación que no lo declaró al empezar: supersede enlaza las dos importaciones.
        spec_3 = self.collars(label="collares-v2", crs_v=WORKS)
        self.assertEqual(self.classify(spec_3), registry.Substitute(
            v2, (registry.Difference("crs_v", REDNAP, WORKS),)
        ))
        self.detect(v2.uid, _sha("collares-v2b"))
        v3, op3 = self.load(spec_3, ROWS_V2, table="res_collares_3", dataset="res_collares",
                            previous=v2.uid, reason=REASON)
        self.assertEqual(self.rows("gb_operation", "uid = ?", (op2.uid,))[0]["superseded_by"],
                         op3.uid)
        data_3 = self.dataset("res_collares")
        self.assertEqual(self.successor(data_1["uid"]), data_3.uid)
        self.assertEqual(self.successor(data_2.uid), data_3.uid)
        self.assertEqual(
            [(row["name"], row["status"], row["previous_uid"]) for row in self.rows("gb_input")],
            [("collares", "superseded", None), ("collares", "superseded", v1.uid),
             ("collares", "current", v2.uid)],
        )
        self.assertEqual(
            [(row["name"], row["status"], row["input_uid"]) for row in self.rows("gb_dataset")],
            [("res_collares", "superseded", v1.uid), ("res_collares", "superseded", v2.uid),
             ("res_collares", "current", v3.uid)],
        )
        (_first, second) = self.logged(events.EventKind.INPUT_UPDATED)
        self.assertEqual((second.entity_uid, second.data["from_status"],
                          second.data["previous_operation_uid"]), (v2.uid, "changed", op2.uid))
        for table, uid, rows in (("res_collares_1", v1.uid, ROWS_V1),
                                 ("res_collares_2", v2.uid, ROWS_V2),
                                 ("res_collares_3", v3.uid, ROWS_V2)):
            with self.subTest(copy=table):
                self.assertEqual([row[1:] for row in self.table(table)],
                                 [(uid, *row) for row in rows])
        stored = [self.rows(name) for name in ("gb_input", "gb_dataset")]
        shown = [[item.message, item.data] for item in self.logged(None)]
        self.assertEqual(paths.find_absolute_paths([stored, shown]), [])

    def test_superseded_rows_stay_in_common_table_out_of_accumulated(self) -> None:
        """RF-008-11, RF-008-52 (plan §5.4.8, «Acumular»): con dos entradas importadas a una
        misma tabla, sustituir una deja sus filas en la tabla, intactas y protegidas, y fuera
        del dato acumulado, cuyo contenido nuevo (las filas de la otra y de la sustituta)
        registra la importación que lo provoca; lo importado de la otra no cambia."""
        a, op_a = self.load(self.collars(name="ensayos_a", label="a"), ROWS_V1,
                            table=SHARED_TABLE, dataset="res_ensayos_a", shared=True)
        b, op_b = self.load(self.collars(name="ensayos_b", label="b"), ROWS_B,
                            table=SHARED_TABLE, dataset="res_ensayos_b", shared=True)
        accumulated = self.dataset(SHARED_TABLE)
        imported_a = self.dataset("res_ensayos_a")
        imported_b = self.rows("gb_dataset", "name = 'res_ensayos_b'")
        rows_a = self.table(SHARED_TABLE, "input_uid = ?", (a.uid,))
        a2, op_a2 = self.load(self.collars(name="ensayos_a", label="a2"), ROWS_V2,
                              table=SHARED_TABLE, dataset="res_ensayos_a", shared=True,
                              previous=a.uid, reason=UPDATE_REASON)
        self.assertEqual(self.table(SHARED_TABLE, "input_uid = ?", (a.uid,)), rows_a)
        for uid, name in ((a.uid, "ensayos_a"), (b.uid, "ensayos_b"), (a2.uid, "ensayos_a")):
            with self.subTest(protected=uid):
                self.assertIn(f"«{name}»", self.foreign_update(SHARED_TABLE, uid))
        self.assertEqual(self.table(SHARED_TABLE, "input_uid = ?", (a.uid,)), rows_a)
        after_a = self.read(lambda conn: datasets.get(conn, imported_a.uid))
        self.assertEqual((after_a.status, after_a.content_sha256),
                         (datasets.DatasetStatus.SUPERSEDED, imported_a.content_sha256))
        self.assertEqual(self.rows("gb_dataset", "name = 'res_ensayos_b'"), imported_b)
        self.assertEqual(self.successor(imported_a.uid), self.dataset("res_ensayos_a").uid)

        # El acumulado: las filas de B y de la sustituta, ni una de la sustituida.
        def control(conn: sqlite3.Connection) -> str:
            _write_rows(conn, "res_control", b.uid, ROWS_B)
            _write_rows(conn, "res_control", a2.uid, ROWS_V2)
            request = builtin.GPKG_LAYER.request("table", {}, {"main": self.project.database_path},
                                                 {"layer": "res_control"})
            for _ in builtin.layer_steps(conn, request):
                pass
            return request.hasher.digest().content_sha256

        expected = self.write(control)
        now = self.dataset(SHARED_TABLE)
        self.assertEqual((now.uid, now.content_sha256, now.operation_uid),
                         (accumulated.uid, expected, op_a2.uid))
        self.assertNotEqual(accumulated.content_sha256, expected)
        self.assertEqual(
            [row["operation_uid"]
             for row in self.rows("gb_dataset_change", "dataset_uid = ?", (accumulated.uid,))],
            [op_a.uid, op_b.uid, op_a2.uid],
        )

    def test_supersede_is_checked_before_writing(self) -> None:
        """RF-008-11: sustituir exige una entrada del proyecto que siga activa, el motivo y la
        importación en curso que la sustituye, y que su importación no la esté sustituyendo
        otra; si no, se rechaza sin escribir nada. Una entrada que dice sustituir a otra que
        sigue activa es un error del programa."""
        v1, op1 = self.load(self.collars(), ROWS_V1, table="res_collares_1",
                            dataset="res_collares")
        other = self.register(self.boundary())
        handle = self.begin()
        error = self.refused(ProvenanceError, "core.input_unknown",
                             self.supersede(UNKNOWN_UID, handle.uid))
        self.assertEqual(str(error), f"No hay ninguna entrada {UNKNOWN_UID} en el proyecto "
                                     f"«{self.project.name}».")
        for reason in (None, "  "):
            with self.subTest(reason=reason):
                error = self.refused(ProvenanceError, "core.input_supersede_reason_missing",
                                     self.supersede(v1.uid, handle.uid, reason))
        self.assertEqual(str(error), "Indique el motivo de la sustitución de la entrada "
                                     "«collares».")
        self.refused(ProvenanceError, "core.operation_unknown",
                     self.supersede(v1.uid, UNKNOWN_UID))
        self.refused(ProvenanceError, "core.operation_not_running",
                     self.supersede(v1.uid, op1.uid))
        # La importación que sustituye declara otra operación sustituida: error del programa.
        elsewhere = operations.begin_operation(self.project, IMPORT.op_type, settings={},
                                               executor="blender",
                                               supersedes=other.operation_uid)
        self.refused(ValueError, None, self.supersede(v1.uid, elsewhere.uid))
        # Otra reimportación en curso ya la está sustituyendo.
        operations.begin_operation(self.project, IMPORT.op_type, settings={},
                                   executor="blender", supersedes=op1.uid)
        error = self.refused(ProvenanceError, "core.operation_already_superseded",
                             self.supersede(v1.uid, handle.uid))
        self.assertEqual(error.values["supersedes"], op1.uid)
        # Una entrada cuya importación no terminó (registrada sin completarla).
        pending = self.begin()
        half = self.write(lambda conn: registry.register_input(
            conn, self.project, self.collars(name="a_medias", label="a-medias"),
            operation_uid=pending.uid))
        self.refused(ProvenanceError, "core.operation_supersedes_not_done",
                     self.supersede(half.uid, handle.uid))
        for args, kw in (((1,), {"operation_uid": handle.uid, "reason": REASON}),
                         ((v1.uid,), {"operation_uid": None, "reason": REASON}),
                         ((v1.uid,), {"operation_uid": handle.uid, "reason": 3})):
            with self.subTest(args=args, kw=kw):
                self.refused(TypeError, None, lambda conn, a=args, k=kw: registry.supersede(
                    conn, self.project, *a, **k))
        with self.assertRaises(ValueError):
            self.read(self.supersede(v1.uid, handle.uid))
        # Registrar una entrada que dice sustituir a otra que sigue activa.
        self.rejected(ValueError, None, self.collars(name="collares_2", label="collares-v2"),
                      operation_uid=handle.uid, previous_uid=v1.uid, reason=REASON)
        # Una entrada sustituida o descartada no se vuelve a sustituir.
        self.write(lambda conn: registry.discard(conn, self.project, other.uid, DISCARD_REASON))
        error = self.refused(ProvenanceError, "core.input_previous_discarded",
                             self.supersede(other.uid, handle.uid))
        self.assertEqual(str(error), "La entrada «Limites_v1» está descartada: queda como "
                                     "registro y no se actualiza.")
        c1 = self.register(self.collars(name="otras", label="otras"))
        newer = self.begin()
        self.write(self.supersede(c1.uid, newer.uid))
        error = self.refused(ProvenanceError, "core.input_superseded",
                             self.supersede(c1.uid, handle.uid))
        self.assertEqual(str(error), "La entrada «otras» ya está sustituida: queda como "
                                     "historia y no cambia.")
        self.assertEqual(self.rows("gb_input", "uid = ?", (v1.uid,))[0]["status"], "current")


class KeepCopyTest(LifecycleCase):
    def test_keep_copy_records_who_and_when(self) -> None:
        """RF-008-12: mantener la copia de una entrada cambiada la deja «cambiada · se
        mantiene la copia» con quién y cuándo (y el motivo, si lo hay, sin rutas absolutas),
        el contenido visto y lo demás igual, y con el evento ``input_kept``; sigue activa y lo
        importado sigue vigente. Solo se decide sobre una entrada cambiada: una vigente, una
        que ya mantiene la copia, una sustituida o una descartada se rechazan sin escribir
        nada."""
        v1, _op1 = self.load(self.collars(), ROWS_V1, table="res_collares_1",
                             dataset="res_collares")
        keep = (lambda uid, **kw: lambda conn: registry.keep_copy(conn, self.project, uid, **kw))
        error = self.refused(ProvenanceError, "core.input_not_changed", keep(v1.uid))
        self.assertEqual(str(error), "La entrada «collares» no ha cambiado: no hay ningún cambio "
                                     "que decidir.")
        seen = _sha("collares-redibujados")
        self.detect(v1.uid, seen)
        before = self.rows("gb_input", "uid = ?", (v1.uid,))[0]
        data = self.rows("gb_dataset")
        moment = self.later()
        record = self.write(keep(v1.uid))
        self.assertEqual(self.rows("gb_input", "uid = ?", (v1.uid,)), [{
            **before, "status": "kept", "status_at": moment, "status_by": SESSION.user_host,
            "status_reason": None, "modified_at": moment,
        }])
        self.assertEqual((record.status, record.active, record.seen_sha256),
                         (model.InputStatus.KEPT, True, seen))
        self.assertEqual(self.rows("gb_dataset"), data)
        (event,) = self.logged(events.EventKind.INPUT_KEPT)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.user_host),
                         ("input", v1.uid, moment, SESSION.user_host))
        self.assertEqual(event.message, "Entrada «collares»: cambiada · se mantiene la copia.")
        self.assertEqual(event.data, {"name": "collares", "seen_sha256": seen,
                                      "content_sha256": v1.content_sha256, "reason": None})
        error = self.refused(ProvenanceError, "core.input_already_kept", keep(v1.uid))
        self.assertEqual(str(error), "La entrada «collares» ya está «cambiada · se mantiene la "
                                     "copia».")
        # Su fuente cambia otra vez: se vuelve a decidir, ahora con motivo.
        self.detect(v1.uid, _sha("collares-otra-vez"))
        record = self.write(keep(v1.uid, reason=f"{UPDATE_REASON}  "))
        self.assertEqual((record.status, record.status_reason, record.seen_sha256),
                         (model.InputStatus.KEPT, UPDATE_REASON_STORED,
                          _sha("collares-otra-vez")))
        # Sin el contenido visto no hay cambio que mantener: error del programa.
        other = self.register(self.collars(name="otras", label="otras"))
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'changed' WHERE uid = ?", (other.uid,)))
        self.refused(ValueError, None, keep(other.uid))
        self.refused(TypeError, None, keep(other.uid, reason=3))
        self.refused(ProvenanceError, "core.input_unknown", keep(UNKNOWN_UID))
        self.write(lambda conn: registry.discard(conn, self.project, other.uid, DISCARD_REASON))
        error = self.refused(ProvenanceError, "core.input_discarded", keep(other.uid))
        self.assertEqual(str(error), "La entrada «otras» está descartada: queda como registro y "
                                     "no cambia.")
        newer = self.begin()
        self.write(self.supersede(v1.uid, newer.uid))
        self.refused(ProvenanceError, "core.input_superseded", keep(v1.uid))
        with self.assertRaises(ValueError):
            self.read(keep(v1.uid))


class DiscardTest(LifecycleCase):
    def test_discard_with_reason_marks_input_and_its_data(self) -> None:
        """RF-008-55, RF-008-52: descartar una entrada, con motivo obligatorio, la deja
        «descartada» con quién, cuándo y el motivo, y lo importado de ella «descartado» con su
        contenido y sus filas protegidas; no se borra nada, lo de las demás entradas no cambia,
        libera su nombre lógico, no se reutiliza ni tiene sucesor, y queda el evento
        ``input_discarded``. Una ya descartada o sustituida, o sin motivo, se rechaza sin
        escribir nada."""
        v1, _op1 = self.load(self.collars(), ROWS_V1, table="res_collares_1",
                             dataset="res_collares")
        other, _op = self.load(self.collars(name="otras", label="otras"), ROWS_B,
                               table="res_otras", dataset="res_otras")
        discard = (lambda uid, reason=DISCARD_REASON:
                   lambda conn: registry.discard(conn, self.project, uid, reason))
        for reason in (None, "   "):
            with self.subTest(reason=reason):
                error = self.refused(ProvenanceError, "core.input_discard_reason_missing",
                                     discard(v1.uid, reason))
        self.assertEqual(str(error), "Indique el motivo para descartar la entrada «collares».")
        self.refused(ProvenanceError, "core.input_unknown", discard(UNKNOWN_UID))
        self.refused(TypeError, None, discard(v1.uid, 3))
        with self.assertRaises(ValueError):
            self.read(discard(v1.uid))
        before = self.rows("gb_input", "uid = ?", (v1.uid,))[0]
        data_1 = self.rows("gb_dataset", "input_uid = ?", (v1.uid,))[0]
        data_other = self.rows("gb_dataset", "input_uid = ?", (other.uid,))
        rows_1 = self.table("res_collares_1")
        counts = [len(self.rows(table)) for table in TABLES if table != "gb_event"]
        moment = self.later()
        record = self.write(discard(v1.uid, f"  {DISCARD_REASON} "))
        self.assertEqual(self.rows("gb_input", "uid = ?", (v1.uid,)), [{
            **before, "status": "discarded", "status_at": moment,
            "status_by": SESSION.user_host, "status_reason": DISCARD_REASON,
            "modified_at": moment,
        }])
        self.assertEqual((record.status, record.active),
                         (model.InputStatus.DISCARDED, False))
        self.assertEqual(self.rows("gb_dataset", "input_uid = ?", (v1.uid,)), [{
            **data_1, "status": "discarded", "modified_at": moment,
        }])
        self.assertEqual(self.rows("gb_dataset", "input_uid = ?", (other.uid,)), data_other)
        self.assertEqual(self.table("res_collares_1"), rows_1)
        self.assertIn("«collares»", self.foreign_update("res_collares_1", v1.uid))
        self.assertEqual([len(self.rows(table)) for table in TABLES if table != "gb_event"],
                         counts)
        self.assertIsNone(self.successor(data_1["uid"]))
        (event,) = self.logged(events.EventKind.INPUT_DISCARDED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.user_host),
                         ("input", v1.uid, moment, SESSION.user_host))
        self.assertEqual(event.message, f"Entrada «collares» descartada ({DISCARD_REASON}).")
        self.assertEqual(event.data, {"name": "collares", "from_status": "current",
                                      "reason": DISCARD_REASON, "datasets": [data_1["uid"]]})
        # Queda como registro: su nombre queda libre y no se reutiliza.
        self.assertIsNone(self.read(lambda conn: registry.get(conn, "collares")))
        self.assertEqual(self.classify(self.collars()), registry.New())
        error = self.refused(ProvenanceError, "core.input_discarded", discard(v1.uid))
        self.assertEqual(str(error), "La entrada «collares» está descartada: queda como "
                                     "registro y no cambia.")
        # Una cambiada se puede descartar; una sustituida, no.
        self.detect(other.uid, _sha("otras-cambiadas"))
        newer = self.begin()
        self.write(self.supersede(other.uid, newer.uid))
        error = self.refused(ProvenanceError, "core.input_superseded", discard(other.uid))
        self.assertEqual(str(error), "La entrada «otras» ya está sustituida: queda como "
                                     "historia y no cambia.")
        third = self.register(self.collars(name="terceras", label="terceras"))
        self.detect(third.uid, _sha("terceras-cambiadas"))
        self.assertEqual(self.write(discard(third.uid)).status, model.InputStatus.DISCARDED)
        # Lo importado que falta también se descarta; lo que ya no está vivo no se toca.
        fourth, _op = self.load(self.collars(name="cuartas", label="cuartas"), ROWS_B,
                                table="res_cuartas", dataset="res_cuartas")
        fifth, _op = self.load(self.collars(name="quintas", label="quintas"), ROWS_B,
                               table="res_quintas", dataset="res_quintas")
        for name, status in (("res_cuartas", "missing"), ("res_quintas", "discarded")):
            self.write(lambda conn, n=name, s=status: datasets.set_status(
                conn, self.project, datasets.get(conn, n).uid, s))
        for uid, name in ((fourth.uid, "res_cuartas"), (fifth.uid, "res_quintas")):
            with self.subTest(dataset=name):
                self.write(discard(uid))
                (row,) = self.rows("gb_dataset", "name = ?", (name,))
                self.assertEqual(row["status"], "discarded")
        found = [event.data["datasets"] for event in self.logged(events.EventKind.INPUT_DISCARDED)]
        self.assertEqual(found[-2:], [[self.rows("gb_dataset", "name = 'res_cuartas'")[0]["uid"]],
                                      []])


class ListTest(LifecycleCase):
    def test_register_lists_every_input_by_name(self) -> None:
        """RF-008-16 (plan §5.5, registro de entradas): ``list_inputs`` da todas las entradas
        del proyecto con sus ficheros —también las sustituidas y las descartadas— por su
        nombre lógico (sin distinguir mayúsculas) y, con el mismo nombre, por orden de
        registro; solo lee."""
        self.assertEqual(self.read(registry.list_inputs), [])
        v1, _op = self.load(self.collars(), ROWS_V1, table="res_collares_1",
                            dataset="res_collares")
        boundary = self.register(self.boundary())
        v2, _op = self.load(self.collars(label="collares-v2"), ROWS_V2, table="res_collares_2",
                            dataset="res_collares", previous=v1.uid, reason=UPDATE_REASON)
        self.write(lambda conn: registry.discard(conn, self.project, boundary.uid,
                                                 DISCARD_REASON))
        snapshot = self.snapshot()
        listed = self.read(registry.list_inputs)
        self.assertEqual([(item.uid, item.name, item.status) for item in listed],
                         [(v1.uid, "collares", model.InputStatus.SUPERSEDED),
                          (v2.uid, "collares", model.InputStatus.CURRENT),
                          (boundary.uid, "Limites_v1", model.InputStatus.DISCARDED)])
        self.assertEqual(listed, [self.read(lambda conn, uid=item.uid: registry.get(conn, uid))
                                  for item in listed])
        self.assertTrue(all(item.files for item in listed))
        self.assertEqual(self.snapshot(), snapshot)


class EditDeliveryTest(LifecycleCase):
    def test_edit_changes_name_and_delivery_only(self) -> None:
        """RF-008-07 (D-11; spec §11): editar una entrada cambia su nombre lógico, su fecha de
        entrega y quién la entrega, y nada más (la entrada es la misma: se reutiliza igual y
        sus ficheros no cambian), con el evento ``input_edited``; un nombre de otra entrada
        activa o un valor mal formado se rechazan sin escribir nada, y sin cambios no se
        escribe nada."""
        v1 = self.register(self.boundary())
        self.register(self.collars())
        edit = (lambda uid, **kw: lambda conn: registry.edit_delivery(conn, self.project, uid,
                                                                      **kw))
        before = self.rows("gb_input", "uid = ?", (v1.uid,))[0]
        files = self.rows("gb_input_file")
        moment = self.later()
        record = self.write(edit(v1.uid, name="Limites_propiedad",
                                 received_at=dt.date(2026, 9, 30),
                                 received_from="Topografía de la propiedad"))
        self.assertEqual(self.rows("gb_input", "uid = ?", (v1.uid,)), [{
            **before, "name": "Limites_propiedad", "received_at": "2026-09-30",
            "received_from": "Topografía de la propiedad", "modified_at": moment,
        }])
        self.assertEqual(self.rows("gb_input_file"), files)
        self.assertEqual(self.classify(self.boundary()), registry.Reuse(record))
        self.assertEqual(self.read(lambda conn: registry.get(conn, "Limites_propiedad")).uid,
                         v1.uid)
        self.assertIsNone(self.read(lambda conn: registry.get(conn, "Limites_v1")))
        (event,) = self.logged(events.EventKind.INPUT_EDITED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.user_host),
                         ("input", v1.uid, moment, SESSION.user_host))
        self.assertEqual(event.message, "Entrada «Limites_propiedad» editada: nombre lógico, "
                                        "fecha de entrega y quién la entrega.")
        self.assertEqual(event.data, {"name": "Limites_propiedad", "changes": {
            "name": ["Limites_v1", "Limites_propiedad"],
            "received_at": ["2026-09-24", "2026-09-30"],
            "received_from": ["La propiedad", "Topografía de la propiedad"],
        }})
        # Solo lo que se indica; None quita la entrega; sin cambios, nada.
        record = self.write(edit(v1.uid, received_from=None, received_at="2026-09-29"))
        self.assertEqual((record.name, record.received_at, record.received_from),
                         ("Limites_propiedad", "2026-09-29", None))
        snapshot = self.snapshot()
        self.assertEqual(self.write(edit(v1.uid, name="Limites_propiedad", received_from=None)),
                         record)
        self.assertEqual(self.write(edit(v1.uid)), record)
        self.assertEqual(self.snapshot(), snapshot)
        error = self.refused(ProvenanceError, "core.input_name_taken", edit(v1.uid,
                                                                            name="collares"))
        self.assertEqual(str(error), "Ya hay otra entrada «collares» en el proyecto: elija otro "
                                     "nombre o actualice esa entrada.")
        drive = _other_drive(self.project.root)
        for error_type, kw in ((ValueError, {"name": ""}),
                               (ValueError, {"name": " Limites"}),
                               (TypeError, {"name": 3}),
                               (ValueError, {"name": f"{drive}\\entregas\\Limites"}),
                               (ValueError, {"received_at": "29/09/2026"}),
                               (TypeError, {"received_at": dt.datetime(2026, 9, 29,
                                                                       tzinfo=dt.UTC)}),
                               (ValueError, {"received_from": ""}),
                               (ValueError, {"received_from": f"{drive}\\entregas\\topografia"})):
            with self.subTest(kw=kw):
                self.refused(error_type, None, edit(v1.uid, **kw))
        self.refused(ProvenanceError, "core.input_unknown", edit(UNKNOWN_UID, name="X"))
        with self.assertRaises(ValueError):
            self.read(edit(v1.uid, name="Otro"))
        # La entrega de una entrada descartada también se corrige; su nombre sigue libre.
        self.write(lambda conn: registry.discard(conn, self.project, v1.uid, DISCARD_REASON))
        record = self.write(edit(v1.uid, received_from="La propiedad"))
        self.assertEqual((record.status, record.received_from),
                         (model.InputStatus.DISCARDED, "La propiedad"))
        self.refused(ProvenanceError, "core.input_name_taken", edit(v1.uid, name="collares"))
        collars = self.read(lambda conn: registry.get(conn, "collares"))
        renamed = self.write(edit(collars.uid, name="Limites_propiedad"))
        self.assertEqual((renamed.uid, renamed.name, renamed.status),
                         (collars.uid, "Limites_propiedad", model.InputStatus.CURRENT))


class ModelTest(InputsCase):
    def test_spec_is_checked(self) -> None:
        """RF-008-07: una declaración mal formada es un error del programa (``TypeError`` o
        ``ValueError``) y no llega a registrarse: nombre, tipo, módulo, lector con versión,
        ficheros (rutas relativas, el principal el primero y solo uno, anclas y referencias),
        huellas, CRS con una de las formas del esquema, ajustes sin rutas absolutas, ajustes que
        son contenido entre los ajustes, entrega, y hashes de sus datos con sus declaraciones y
        su lector."""
        good = self.collars()
        drive = _other_drive(self.project.root)
        main = model.SourceFile(COLLARS_PATH, "main", "original")
        sidecar = model.SourceFile("../../fuentes/collares.txt", "sidecar", "original")
        printed = model.SourcePrint(_sha("x"), size=1, mtime_ns=MTIME_NS)
        bare = model.input_declarations(ETRS89, REDNAP, {})
        cases: tuple[tuple[type[BaseException], dict[str, Any]], ...] = (
            (ValueError, {"name": ""}),
            (ValueError, {"name": " collares"}),
            (TypeError, {"name": 3}),
            (ValueError, {"name": f"{drive}\\fuentes\\collares"}),
            (ValueError, {"kind": "block_model"}),
            (TypeError, {"kind": None}),
            (ValueError, {"module": "xyz"}),
            (ValueError, {"reader": "test.source"}),
            (ValueError, {"files": []}),
            (TypeError, {"files": "collares.csv"}),
            (TypeError, {"files": [(COLLARS_PATH, "main", "original")]}),
            (ValueError, {"files": [sidecar, main], "file_prints": [printed, printed]}),
            (ValueError, {"files": [main, main], "file_prints": [printed, printed]}),
            (ValueError, {"files": [main, dataclasses.replace(main, role="sidecar")],
                          "file_prints": [printed, printed]}),
            (ValueError, {"files": [main, dataclasses.replace(sidecar, role="main")],
                          "file_prints": [printed, printed]}),
            (ValueError, {"file_prints": []}),
            (TypeError, {"file_prints": [_sha("x")]}),
            (ValueError, {"file_prints": [model.SourcePrint(_sha("x"))]}),
            (ValueError, {"files": [main, model.SourceFile("res_capa", "sidecar",
                                                           "project_table")],
                          "file_prints": [printed, model.SourcePrint(_sha("y"))]}),
            (ValueError, {"files": [model.SourceFile("res_capa", "main", "project_table")],
                          "file_prints": [printed]}),
            (ValueError, {"crs_h": {"epsg": 0}}),
            (TypeError, {"crs_h": {"epsg": "25830"}}),
            (ValueError, {"crs_h": {"local": "rejilla de mina"}}),
            (ValueError, {"crs_h": {"epsg": 25830, "wkt2": "PROJCRS[]"}}),
            (TypeError, {"crs_h": "EPSG:25830"}),
            (ValueError, {"crs_v": {"not_applicable": False}}),
            (ValueError, {"crs_v": {"wkt2": "VERTCRS[]"}}),
            (ValueError, {"crs_v": {"local": ""}}),
            (TypeError, {"settings": [("units", "m")]}),
            (TypeError, {"settings": {"units": {"m"}}}),
            (ValueError, {"settings": {"units": "m", "ruta": f"{drive}\\fuentes\\collares.csv"}}),
            (ValueError, {"content_settings_keys": ("units", "cota")}),
            (TypeError, {"content_settings_keys": "units"}),
            (ValueError, {"layer": ""}),
            (ValueError, {"received_at": "24/09/2026"}),
            (TypeError, {"received_at": dt.datetime(2026, 9, 24, tzinfo=dt.UTC)}),
            (ValueError, {"received_from": ""}),
            (TypeError, {"digest": _sha("x")}),
            (ValueError, {"digest": dataclasses.replace(good.digest, reader="test.other@1")}),
            (ValueError, {"digest": _digest("collares", "table", bare)}),
        )
        for error, changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(error):
                    dataclasses.replace(good, **changes)
        files = (
            (ValueError, (f"{drive}/fuentes/x.csv", "main", "original")),
            (ValueError, ("fuentes\\x.csv", "main", "project")),
            (ValueError, ("../x.csv", "main", "project")),
            (ValueError, ("/fuentes/x.csv", "main", "original")),
            (ValueError, ("x.csv", "main", "external")),
            (ValueError, ("dir/x.csv", "main", "external", "a1b2")),
            (ValueError, ("x.csv", "main", "original", "a1b2")),
            (ValueError, ("x.csv", "principal", "original")),
            (ValueError, ("x.csv", "main", "nas")),
            (ValueError, ("", "main", "project_table")),
            (TypeError, (1, "main", "original")),
        )
        for error, values in files:
            with self.subTest(file=values):
                with self.assertRaises(error):
                    model.SourceFile(*values[:3], ref_uid=values[3] if len(values) > 3 else None)
        prints = (
            (ValueError, ("abc",), {}),
            (ValueError, (_sha("x"),), {"size": -1, "mtime_ns": MTIME_NS}),
            (TypeError, (_sha("x"),), {"size": 1.5, "mtime_ns": MTIME_NS}),
            (TypeError, (_sha("x"),), {"size": 1, "mtime_ns": True}),
        )
        for error, args, kw in prints:
            with self.subTest(print=(args, kw)):
                with self.assertRaises(error):
                    model.SourcePrint(*args, **kw)
        crs_cases = (
            (ValueError, {"epsg": 0}, "horizontal"),
            (TypeError, {"epsg": "25830"}, "horizontal"),
            (TypeError, {"epsg": True}, "vertical"),
            (ValueError, {"local": "rejilla de mina"}, "horizontal"),
            (ValueError, {"ellipsoidal": 4937}, "horizontal"),
            (ValueError, {"epsg": 25830, "wkt2": "PROJCRS[]"}, "horizontal"),
            (ValueError, {}, "horizontal"),
            (TypeError, "EPSG:25830", "horizontal"),
            (ValueError, {"not_applicable": False}, "vertical"),
            (ValueError, {"not_applicable": 1}, "vertical"),
            (ValueError, {"wkt2": "VERTCRS[]"}, "vertical"),
            (ValueError, {"local": ""}, "vertical"),
            (ValueError, {"local": f"{drive}\\obra\\cotas.txt"}, "vertical"),
            (ValueError, {"ellipsoidal": 0}, "vertical"),
            (ValueError, ETRS89, "diagonal"),
        )
        for error, crs, axis in crs_cases:
            with self.subTest(crs=crs, axis=axis):
                with self.assertRaises(error):
                    model.check_crs(crs, axis)
        for crs, axis in ((ETRS89, "horizontal"), ({"wkt2": "PROJCRS[]"}, "horizontal"),
                          (NOT_APPLICABLE, "horizontal"), (REDNAP, "vertical"),
                          (WORKS, "vertical"), ({"ellipsoidal": "ETRS89"}, "vertical"),
                          ({"ellipsoidal": 4937}, "vertical"), (NOT_APPLICABLE, "vertical"),
                          (None, "vertical")):
            with self.subTest(admitted=crs, axis=axis):
                self.assertEqual(model.check_crs(crs, axis), crs)
        self.assertEqual(
            [model.crs_text(crs) for crs in (ETRS89, {"wkt2": "PROJCRS[]"}, WORKS,
                                             {"ellipsoidal": 4937}, NOT_APPLICABLE, None)],
            ["EPSG:25830", "WKT2", "local «cota de obra»", "elipsoidal (EPSG:4937)", "no aplica",
             "—"],
        )
        with self.assertRaises(TypeError):
            self.classify("collares")
        self.rejected(TypeError, None, "collares")
        self.assertEqual(self.rows("gb_input"), [])

    def test_vocabulary(self) -> None:
        """RF-008-07: estados, tipos, papeles, anclas y original son los del esquema 2 (las
        anclas, las ubicaciones de los lectores, y los estados inactivos, los que liberan el
        nombre lógico); los tipos con coordenadas exigen CRS horizontal y los que tienen cota,
        vertical; dos eventos nuevos."""
        ddl = schema.TABLES["gb_input"]
        file_ddl = schema.TABLES["gb_input_file"]
        self.assertEqual([str(item) for item in model.InputStatus], _check_list(ddl, "status"))
        self.assertEqual(list(model.INPUT_KINDS), _check_list(ddl, "kind"))
        self.assertEqual([str(item) for item in model.OriginalState],
                         _check_list(ddl, "original"))
        self.assertEqual([str(item) for item in model.FileRole], _check_list(file_ddl, "role"))
        self.assertEqual([str(item) for item in model.FileAnchor],
                         _check_list(file_ddl, "anchor"))
        self.assertEqual(tuple(model.FileAnchor), readers.LOCATIONS)
        self.assertEqual(tuple(model.INACTIVE_STATUSES), schema.INACTIVE_INPUT_STATUSES)
        self.assertEqual(set(model.ACTIVE_STATUSES) | set(model.INACTIVE_STATUSES),
                         set(model.InputStatus))
        self.assertTrue(set(model.INPUT_KINDS) <= content.KINDS)
        self.assertEqual(model.COORDINATE_KINDS,
                         ("raster", "vector", "drillholes", "mesh", "point_cloud"))
        self.assertEqual(model.ELEVATION_KINDS, ("drillholes", "mesh", "point_cloud"))
        self.assertEqual(
            [events.EventKind[name].value
             for name in ("INPUT_REGISTERED", "INPUT_REUSED", "INPUT_UPDATED", "INPUT_KEPT",
                          "INPUT_DISCARDED", "INPUT_EDITED")],
            ["input_registered", "input_reused", "input_updated", "input_kept",
             "input_discarded", "input_edited"],
        )
        self.assertIs(inputs.register_input, registry.register_input)
        self.assertIs(inputs.InputSpec, model.InputSpec)
        for name in ("supersede", "keep_copy", "discard", "edit_delivery"):
            with self.subTest(function=name):
                self.assertIs(getattr(inputs, name), getattr(registry, name))


if __name__ == "__main__":
    unittest.main()

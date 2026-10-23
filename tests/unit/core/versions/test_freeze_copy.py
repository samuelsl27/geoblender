# SPDX-License-Identifier: GPL-3.0-or-later
"""La copia de una instantánea por pasos y su confirmación (spec 009, T12, T13 y T33; RF-009-06,
RF-009-07, RNF-009-06; plan 009 A6, A7, §5.2.4, §5.2.5, D-11, D-28, D-29, D-30, D-39, D-40,
D-41; ADR-0026).

``core.versions.copy.copy_steps`` copia lo que dice el plan de una congelación
(``core.versions.freeze.freeze_plan``) a la carpeta temporal de la instantánea
(``snapshots/V01.r1.congelando-<8 hex>/``), sobre el proyecto de la demostración de versiones
(``tests/support/versions_fixtures.py``):

1. cada rejilla y cada malla, con su huella, ``fsync`` cada 32 MiB y al final, y el hash de
   contenido de la copia (con el lector y el normalizador de su dato) igual al registrado;
2. las tablas y capas, en un GeoPackage 1.4 armado en la caché (las de un selector, solo sus
   filas), sin disparadores, en diario clásico, con el CRS del proyecto y el hash de cada una
   igual al registrado (también una capa con geometría);
3. el manifiesto de §5.2.5, compacto y sin rutas absolutas; ningún Parquet (ADR-0026);
4. lo ya copiado en otra revisión, referenciado y no copiado; una revisión vacía, solo su
   manifiesto (D-41);
5. cancelar en cada fase, un dato que cambia mientras se copia (otra conexión, como QGIS), una
   copia que no tiene el contenido registrado y la falta de espacio: no queda nada (la temporal,
   borrada) y nada se escribe en la base; el progreso de cada paso; renombrar la temporal sin
   sustituir los restos de otra congelación;
6. congelar de verdad (``core.versions.freeze.freeze_steps``: el plan, la copia y la
   confirmación, A7): la revisión congelada con sus elementos, su huella, sus bytes, lo
   aceptado y la versión de Geoblender, y la siguiente abierta con su motivo, en una sola
   transacción; la cabecera con su inventario (y, si no se pudo escribir, regenerada al abrir);
   una revisión vacía; lo que hay que aceptar y lo que lo impide; una operación terminada
   entretanto que cambió algo congelado cancela (D-40); un cierre a medias va a ``orphans/`` al
   abrir sin borrar nada, y la temporal de esta sesión no se aparta; lo que crece el proyecto
   (RNF-009-06, preliminar);
7. el formato compacto (T33, RNF-009-06): el evento ``revision_frozen`` sin la lista de lo
   referenciado (está en ``gb_revision_item``) y el manifiesto sin lo que vale lo de por
   defecto y con cada fichero de otra instantánea una vez, leído entero como el de la T13
   (``model.expand_manifest``).

Datos solo sintéticos.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import time
import types
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_demo as demo_support
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.package import import_geoblender

copy_mod = import_geoblender("core.versions.copy")
freeze = import_geoblender("core.versions.freeze")
freezing = import_geoblender("core.versions.freezing")
model = import_geoblender("core.versions.model")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
dataset_model = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")
versions_read = import_geoblender("core.versions.read")
events_mod = import_geoblender("core.project.events")
session_mod = import_geoblender("core.project.session")
open_mod = import_geoblender("core.project.open")
errors = import_geoblender("core.errors")
orphans = import_geoblender("core.datasets.orphans")
version_mod = import_geoblender("core.version")
project_model = import_geoblender("core.project.model")

ItemKind = model.ItemKind
ItemPart = model.ItemPart
EVENT = events_mod.EventKind
TINY = 1e-9
"""Un presupuesto por paso tan pequeño que cada paso de dentro da su ``Progress``."""
MB = 1_000_000
"""RNF-009-06: lo que puede crecer el proyecto además de lo copiado (1 MB)."""
HOUR_NS = 3600 * 10**9
TABLES = (vdemo.PIT_BENCHES, vdemo.PIT_STOCKPILES_TABLE, vdemo.SKETCH_LAYER)
"""Las tablas y capas de V01 que copia la instantánea, además de las de aguas arriba."""
UPSTREAM_TABLES = (demo_support.STOCKPILES_TABLE, demo_support.CANDIDATES_TABLE,
                   demo_support.YEARS_TABLE, demo_support.BENCHES_TABLE,
                   demo_support.MARKS_TABLE)
"""Lo derivado o editable del proyecto aguas arriba de ``demo.pit_stockpiles``."""
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _strings(value: Any) -> Iterator[str]:
    """Todos los textos de un JSON (claves y valores)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FreezeCopyCase(fixtures.VersionsProjectCase):
    """Ayudas para las pruebas de la copia de una instantánea."""

    def plan(self, version: str = "V01") -> Any:
        return freeze.freeze_plan(self.project, version)

    def cache(self) -> Path:
        return Path(self.project.cache_dir())

    def steps(self, plan: Any, **kw: Any) -> tuple[Iterator[Any], Path]:
        """Los pasos de la copia de ``plan`` (un ``Progress`` por paso, salvo otro presupuesto)
        y su carpeta temporal."""
        temporary = copy_mod.temporary_path(self.root, plan.label)
        kw.setdefault("budget_s", TINY)
        return copy_mod.copy_steps(self.project, plan, temporary, self.cache(), **kw), temporary

    def copy(self, plan: Any, *, stop: Callable[[Any], bool] | None = None,
             **kw: Any) -> tuple[list[Any], Path]:
        """La copia hasta el final o, con ``stop``, hasta el paso en que dé verdadero (allí se
        cierra: Esc); los ``Progress`` vistos y la carpeta temporal."""
        steps, temporary = self.steps(plan, **kw)
        seen: list[Any] = []
        try:
            for step in steps:
                seen.append(step)
                if stop is not None and stop(step):
                    break
        finally:
            steps.close()  # type: ignore[attr-defined]
        return seen, temporary

    def finished(self, plan: Any, **kw: Any) -> tuple[Any, list[Any], Path]:
        """La copia entera: su resultado (``SnapshotCopy``), sus pasos y la temporal."""
        seen, temporary = self.copy(plan, **kw)
        self.assertIsNotNone(seen[-1].result)
        self.assertEqual([step.result is not None for step in seen].count(True), 1)
        return seen[-1].result, seen, temporary

    def content(self, record: Any, path: Path, layer: str | None = None) -> str:
        """El hash de contenido de ``path`` (y su capa) con el lector y el normalizador de
        ``record``, sin declaraciones (el de un dato)."""
        declarations = dataset_model.DATASET_DECLARATIONS
        if layer is not None:
            request = builtin.GPKG_LAYER.request(record.kind, declarations, {"main": path},
                                                 {"layer": layer},
                                                 normalizer=record.normalizer)
            return readers.read_content(builtin.GPKG_LAYER, request).content_sha256
        found = readers.reader(record.reader)
        request = found.request(record.kind, declarations, {"main": path},
                                normalizer=record.normalizer)
        return readers.read_content(found, request).content_sha256

    def snapshots(self) -> list[str]:
        """Lo que hay en ``snapshots/`` (la carpeta es del proyecto: está desde que se crea)."""
        return sorted(path.name for path in (self.root / "snapshots").iterdir())

    def state(self) -> tuple[Any, ...]:
        """Lo que no puede cambiar al copiar: los ficheros del proyecto (sin ``snapshots/`` ni
        la caché), el contador de cambios de la base, lo que hay en la caché y en
        ``snapshots/``."""
        cache = self.cache()
        cached = sorted(path.name for path in cache.iterdir()) if cache.is_dir() else None
        return (self.files(skip_dirs=("snapshots", "cache")), self.change_counter(), cached,
                self.snapshots())

    def assertNothingLeft(self, before: tuple[Any, ...], temporary: Path) -> None:  # noqa: N802
        """Ni la temporal (``snapshots/`` como estaba), ni el GeoPackage de la caché, ni nada
        escrito en el proyecto."""
        self.assertFalse(temporary.exists())
        self.assertEqual(self.state(), before)

    def assertRefused(self, code: str, work: Callable[[], Any]) -> Any:  # noqa: N802
        with self.assertRaises(model.VersionError) as caught:
            work()
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(str(caught.exception))
        return caught.exception


class CopyTest(FreezeCopyCase):
    def test_files_tables_and_manifest(self) -> None:
        """RF-009-07, D-28, D-30, ADR-0026 (plan A6 (1) a (3), §5.2.5): con el hueco, su
        volumen, los acopios y las rampas en V01, la copia deja en
        ``snapshots/V01.r1.congelando-<8 hex>/`` la rejilla y la malla (los mismos bytes y la
        misma fecha que en el proyecto, su huella y su hash de contenido = el registrado), el
        GeoPackage de la instantánea con las 8 tablas y capas copiadas (GeoPackage 1.4, diario
        clásico, sin disparadores ni índice espacial, las mismas columnas y filas, la capa de
        rampas con el CRS del proyecto y el hash de cada una = el registrado) y el manifiesto de
        §5.2.5 (compacto, con su huella, sin rutas absolutas); ningún Parquet. ``fsync`` cada
        ``SYNC_BYTES`` y al final de cada fichero. Lo congelado lleva la huella y el tamaño de
        su fichero. El progreso de cada paso; nada escrito en el proyecto ni en la caché; y la
        temporal se renombra a ``snapshots/V01.r1``."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_volume(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        self.demo.sketch(self.project, "V01")
        original = {"path": f"originals/{self.record(self.boundary).input_uid}/Limites_v1.gpkg",
                    "size": 12345, "sha256": "e" * 64}  # el original guardado (RF-008-53)
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input_file SET original_path = ?, original_size = ?, original_sha256 = ? "
            "WHERE input_uid = ? AND ord = (SELECT min(ord) FROM gb_input_file "
            "WHERE input_uid = ?)", (original["path"], original["size"], original["sha256"],
                                     self.record(self.boundary).input_uid,
                                     self.record(self.boundary).input_uid)))
        plan = self.plan()
        before = self.state()
        synced: list[tuple[int, int]] = []
        real_fsync = os.fsync

        def spy(fd: int) -> None:
            stat = os.fstat(fd)
            synced.append((stat.st_ino, stat.st_size))
            real_fsync(fd)

        chunk = 4096
        with mock.patch.object(copy_mod, "CHUNK_BYTES", chunk), \
                mock.patch.object(copy_mod, "SYNC_BYTES", 3 * chunk), \
                mock.patch.object(copy_mod.os, "fsync", spy):
            result, progress, temporary = self.finished(plan)

        self.assertRegex(temporary.name, r"^V01\.r1\.congelando-[0-9a-f]{8}$")
        self.assertEqual(temporary.parent, self.root / "snapshots")
        self.assertEqual((result.temporary, result.label), (temporary, "V01.r1"))
        files = [copy for copy in plan.to_copy if str(copy.record.store) != "gpkg"]
        tables = [copy for copy in plan.to_copy if str(copy.record.store) == "gpkg"]
        self.assertEqual({copy.record.name for copy in files}, {vdemo.PIT_GRID, vdemo.PIT_MESH})
        self.assertEqual({copy.record.name for copy in tables}, {*TABLES, *UPSTREAM_TABLES})
        listed = sorted(path.relative_to(temporary).as_posix()
                        for path in temporary.rglob("*") if path.is_file())
        self.assertEqual(listed, sorted([*(copy.record.locator for copy in files),
                                         "V01.r1.gpkg", "manifest.json"]))
        self.assertFalse([path for path in temporary.rglob("*") if path.suffix == ".parquet"])
        self.assertFalse((self.root / "snapshots" / "V01.r1").exists())

        # Rejilla y malla: los mismos bytes y fecha, su huella, fsync y su hash de contenido.
        own = {item.path: item for item in result.files}
        for copy in files:
            path = temporary / copy.record.locator
            source = self.root / copy.record.locator
            with self.subTest(dataset=copy.record.name):
                self.assertEqual(_sha256(path), _sha256(source))
                self.assertEqual(path.stat().st_mtime_ns, source.stat().st_mtime_ns)
                self.assertEqual(own[copy.record.locator],
                                 copy_mod.SnapshotFile(copy.record.locator, path.stat().st_size,
                                                       _sha256(path)))
                self.assertEqual(self.content(copy.record, path), copy.record.content_sha256)
                size = path.stat().st_size
                sizes = [done for ino, done in synced if ino == path.stat().st_ino]
                sync = 3 * chunk
                self.assertEqual(sizes, [k * sync for k in range(1, size // sync + 1)] + [size])
        mesh = next(copy for copy in files if copy.record.name == vdemo.PIT_MESH)
        self.assertGreater((temporary / mesh.record.locator).stat().st_size, 3 * 3 * chunk)

        # El GeoPackage de la instantánea.
        gpkg = temporary / "V01.r1.gpkg"
        self.assertEqual(own["V01.r1.gpkg"],
                         copy_mod.SnapshotFile("V01.r1.gpkg", gpkg.stat().st_size, _sha256(gpkg)))
        snapshot = sqlite3.connect(f"{gpkg.as_uri()}?mode=ro", uri=True)
        self.addCleanup(snapshot.close)
        self.assertEqual(snapshot.execute("PRAGMA application_id").fetchone()[0],
                         gpkg_base.APPLICATION_ID)
        self.assertEqual(snapshot.execute("PRAGMA user_version").fetchone()[0],
                         gpkg_base.USER_VERSION)
        self.assertEqual(snapshot.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.assertEqual(snapshot.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' "
            "OR name LIKE 'rtree%'").fetchone()[0], 0)
        contents = {str(name): (str(kind), srs) for name, kind, srs in snapshot.execute(
            "SELECT table_name, data_type, srs_id FROM gpkg_contents")}
        self.assertEqual(set(contents), {copy.snapshot_layer for copy in tables})
        epsg = int(self.project.record.crs_epsg)
        with self.project.read() as source:
            for copy in tables:
                layer = str(copy.snapshot_layer)
                record = copy.record
                with self.subTest(table=record.name):
                    self.assertEqual(layer, record.locator)
                    self.assertEqual(self.content(record, gpkg, layer), record.content_sha256)
                    self.assertEqual(
                        snapshot.execute(f'PRAGMA table_info("{layer}")').fetchall(),
                        source.execute(f'PRAGMA table_info("{record.locator}")').fetchall())
                    self.assertEqual(
                        snapshot.execute(f'SELECT * FROM "{layer}" ORDER BY fid').fetchall(),
                        source.execute(f'SELECT * FROM "{record.locator}" ORDER BY fid')
                        .fetchall())
                    kind, srs = contents[layer]
                    if record.kind == "vector":
                        self.assertEqual((kind, srs), ("features", epsg))
                        self.assertEqual(
                            snapshot.execute("SELECT column_name, geometry_type_name, srs_id, "
                                             "z, m FROM gpkg_geometry_columns WHERE "
                                             "table_name = ?", (layer,)).fetchall(),
                            source.execute("SELECT column_name, geometry_type_name, srs_id, "
                                           "z, m FROM gpkg_geometry_columns WHERE "
                                           "table_name = ?", (record.locator,)).fetchall())
                    else:
                        self.assertEqual((kind, srs), ("attributes", None))
            self.assertTrue(any(copy.record.kind == "vector" for copy in tables))
            srs_sql = ("SELECT srs_name, srs_id, organization, organization_coordsys_id, "
                       "definition FROM gpkg_spatial_ref_sys WHERE srs_id = ?")
            self.assertEqual(snapshot.execute(srs_sql, (epsg,)).fetchall(),
                             source.execute(srs_sql, (epsg,)).fetchall())

            # El manifiesto.
            raw = (temporary / copy_mod.MANIFEST_NAME).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), result.manifest_sha256)
            self.assertEqual(len(raw), result.manifest_size)
            body = json.loads(raw)
            self.assertEqual(raw, hashing.canonical_json(body))
            self.assertNotIn(b"\n", raw)
            body = model.expand_manifest(body)  # compacto (T33): leído entero
            self.assertEqual(
                {key: body[key] for key in ("format", "schema", "project_uid", "revision",
                                            "revision_uid", "version_uid", "frozen_at",
                                            "frozen_by", "geoblender_version", "accepted")},
                {"format": "geoblender-snapshot", "schema": 1, "project_uid": self.project.uid,
                 "revision": "V01.r1", "revision_uid": plan.revision.uid,
                 "version_uid": self.v1.uid, "frozen_at": result.frozen_at,
                 "frozen_by": fixtures.USER, "geoblender_version": result.geoblender_version,
                 "accepted": None})
            self.assertEqual(body["files"], [{"path": item.path, "size": item.size,
                                              "sha256": item.sha256} for item in result.files])
            self.assertEqual(sorted(item["path"] for item in body["files"]),
                             sorted(name for name in listed if name != "manifest.json"))
            self.assertEqual(result.copied_bytes, sum(item.size for item in result.files))
            datasets = {entry["uid"]: entry for entry in body["datasets"]}
            dataset_items = [item for item in plan.items if item.item_kind is ItemKind.DATASET]
            self.assertEqual(list(datasets), [item.item_uid for item in dataset_items])
            for item in dataset_items:
                entry = datasets[item.item_uid]
                record = self.record(item.item_uid)
                with self.subTest(manifest=record.name):
                    self.assertEqual(
                        {key: entry[key] for key in ("name", "kind", "reader", "normalizer",
                                                     "content_sha256", "part", "state")},
                        {"name": record.name, "kind": record.kind, "reader": record.reader,
                         "normalizer": record.normalizer, "content_sha256": item.content_sha256,
                         "part": str(item.part), "state": str(item.state)})
                    if item.part is ItemPart.IMMUTABLE:
                        self.assertEqual((entry["location"], entry["layer"]),
                                         ("project", record.locator))
                    elif str(record.store) == "gpkg":
                        self.assertEqual((entry["location"], entry["path"], entry["layer"]),
                                         ("own", "V01.r1.gpkg", record.locator))
                    else:
                        self.assertEqual((entry["location"], entry["path"], entry["layer"]),
                                         ("own", record.locator, None))
            (input_uid,) = [item.item_uid for item in plan.items
                            if item.item_kind is ItemKind.INPUT]
            originals = [{"path": path, "size": size, "sha256": sha}
                         for path, size, sha in source.execute(
                             "SELECT original_path, original_size, original_sha256 FROM "
                             "gb_input_file WHERE input_uid = ? AND original_path IS NOT NULL "
                             "ORDER BY ord", (input_uid,))]
            (content,) = source.execute("SELECT content_sha256 FROM gb_input WHERE uid = ?",
                                        (input_uid,)).fetchone()
            self.assertEqual([{key: entry[key] for key in ("uid", "content_sha256", "originals")}
                              for entry in body["inputs"]],
                             [{"uid": input_uid, "content_sha256": content,
                               "originals": originals}])
            self.assertEqual(originals, [original])
            parameters = {entry["uid"]: entry for entry in body["parameters"]}
            for item in plan.items:
                if item.item_kind is not ItemKind.PARAMETER:
                    continue
                key, scope, scope_uid = source.execute(
                    "SELECT key, scope, scope_uid FROM gb_parameter WHERE uid = ?",
                    (item.item_uid,)).fetchone()
                self.assertEqual(parameters.pop(item.item_uid), {
                    "uid": item.item_uid, "key": key, "scope": scope, "scope_uid": scope_uid,
                    "rev": item.item_rev, "value_sha256": item.content_sha256,
                    "part": str(item.part), "state": str(item.state)})
            self.assertEqual(parameters, {})
            operations = {entry["uid"]: entry for entry in body["operations"]}
            self.assertEqual(set(operations), {item.item_uid for item in plan.items
                                               if item.item_kind is ItemKind.OPERATION})
            for uid, entry in operations.items():
                op_type, op_version = source.execute(
                    "SELECT op_type, op_version FROM gb_operation WHERE uid = ?",
                    (uid,)).fetchone()
                self.assertEqual((entry["op_type"], entry["op_version"]), (op_type, op_version))
                self.assertEqual(entry["reproducible"], op_type in (
                    vdemo.PIT, vdemo.PIT_VOLUME, vdemo.PIT_STOCKPILES), op_type)
            (figure,) = body["figures"]
            key, value, unit, kind = source.execute(
                "SELECT key, value, unit, kind FROM gb_figure WHERE uid = ?",
                (figure["uid"],)).fetchone()
            self.assertEqual(
                {name: figure[name] for name in ("key", "value", "unit", "kind", "scope")},
                {"key": key, "value": value, "unit": unit, "kind": kind, "scope": {}})
        for text in _strings(body):
            self.assertFalse(os.path.isabs(text) or _DRIVE.match(text) or text.startswith("\\")
                             or str(self.folder) in text, text)

        # Lo congelado, con la huella y el tamaño de su fichero; lo demás, como en el plan.
        found = {(item.item_kind, item.item_uid): item for item in result.items}
        self.assertEqual(list(found), [(item.item_kind, item.item_uid) for item in plan.items])
        for item in plan.items:
            copied = found[(item.item_kind, item.item_uid)]
            if item.copied:
                rel = str(item.snapshot_path).removeprefix("snapshots/V01.r1/")
                self.assertEqual((copied.file_sha256, copied.file_size),
                                 (own[rel].sha256, own[rel].size))
                self.assertEqual(dataclasses.replace(copied, file_sha256=None, file_size=None),
                                 item)
            else:
                self.assertEqual(copied, item)

        # El progreso de cada paso.
        phases = [step.phase for step in progress]
        self.assertEqual(list(dict.fromkeys(phases)), list(copy_mod.PHASES))
        self.assertEqual({step.total for step in progress}, {progress[0].total})
        done = [step.done for step in progress]
        self.assertEqual(done, sorted(done))
        self.assertEqual((done[0], done[-1]), (0, progress[-1].total))
        self.assertTrue(all(step.message for step in progress))
        grid = Path(next(copy.record.locator for copy in files
                         if copy.record.name == vdemo.PIT_GRID)).name
        for phase, name in (("copia", grid), ("comprobación", grid),
                            ("tablas", tables[0].record.locator)):
            self.assertTrue(any(step.phase == phase and f"«{name}»" in step.message
                                for step in progress), (phase, name))

        # Nada escrito en el proyecto ni en la caché; la temporal, a su nombre.
        self.assertEqual(self.state()[:3], before[:3])
        snapshot.close()  # en Windows, una carpeta con un fichero abierto no se renombra
        final = copy_mod.rename_snapshot(temporary, self.root / "snapshots" / "V01.r1")
        self.assertEqual(final, self.root / "snapshots" / "V01.r1")
        self.assertFalse(temporary.exists())
        self.assertEqual(sorted(path.relative_to(final).as_posix()
                                for path in final.rglob("*") if path.is_file()), listed)
        self.assertEqual(_sha256(final / copy_mod.MANIFEST_NAME), result.manifest_sha256)


class SelectorTest(FreezeCopyCase):
    def test_only_the_rows_of_its_selector(self) -> None:
        """D-29, RF-009-07, RF-009-08 (plan A6 (2), §5.2.5): dos datos con selector sobre la
        misma tabla del proyecto (``{"column": "grp", "equals": …}``) se copian a dos tablas
        de la instantánea (la segunda, con otro nombre), cada una solo con sus filas y sin
        selector, con el hash de contenido registrado; lo aceptado (la cadena obsoleta por el
        banco cambiado) va al manifiesto con su motivo."""
        self.demo.pit(self.project, "V01")
        benches = self.record(vdemo.PIT_BENCHES, "V01")
        shared = "demo_shared"

        def create(conn: sqlite3.Connection) -> None:
            gpkg_base.create_attribute_table(
                conn, shared, [gpkg_base.ColumnDef("grp", "TEXT"),
                               gpkg_base.ColumnDef("value", "DOUBLE")],
                "Compartida (prueba)", "Tabla sintética con selector")
            conn.executemany(f'INSERT INTO "{shared}" (grp, value) VALUES (?, ?)',
                             [("a", 1.5), ("b", 2.0), ("a", 3.25), ("b", 4.0), ("b", 5.5)])

        self.write(create)

        def selected(group: str, uid: str) -> Any:
            selector = {"column": "grp", "equals": group}
            request = builtin.GPKG_LAYER.request(
                "table", dataset_model.DATASET_DECLARATIONS, {"main": self.project.database_path},
                {"layer": shared, "selector": selector})
            with self.project.read() as conn:
                for _done in builtin.layer_steps(conn, request):
                    pass
            return dataclasses.replace(
                benches, uid=uid, name=f"{shared}_{group}", locator=shared, selector=selector,
                selector_json=hashing.canonical_json(selector).decode(),
                content_sha256=request.hasher.digest().content_sha256)

        first = selected("a", "5e1ec700-0000-4000-8000-00000000000a")
        second = selected("b", "5e1ec700-0000-4000-8000-00000000000b")
        self.bench(12.0)
        plan = self.plan()
        self.assertTrue(plan.accept)
        gpkg_path = f"{plan.snapshot_dir}/{plan.label}.gpkg"
        extra = [freeze.CopyItem(first, ItemPart.UPSTREAM, gpkg_path, shared, 4096),
                 freeze.CopyItem(second, ItemPart.UPSTREAM, gpkg_path,
                                 f"{shared}_{second.uid[:8]}", 4096)]
        plan = dataclasses.replace(
            plan, to_copy=(*plan.to_copy, *extra),
            items=(*plan.items, *(model.RevisionItem(
                plan.revision.uid, ItemKind.DATASET, copy.record.uid, ItemPart.UPSTREAM, None,
                copy.record.content_sha256, True, gpkg_path, copy.snapshot_layer, None, None,
                model.ItemState.CURRENT) for copy in extra)))
        accepted = copy_mod.acceptance(plan, reason="Se entrega con el banco anterior")
        result, _progress, temporary = self.finished(plan, accepted=accepted)

        snapshot = sqlite3.connect(f"{(temporary / 'V01.r1.gpkg').as_uri()}?mode=ro", uri=True)
        self.addCleanup(snapshot.close)
        for copy, group in ((extra[0], "a"), (extra[1], "b")):
            layer = str(copy.snapshot_layer)
            with self.subTest(layer=layer):
                rows = snapshot.execute(f'SELECT fid, grp, value FROM "{layer}" ORDER BY fid')
                expected = self.query(f'SELECT fid, grp, value FROM "{shared}" WHERE grp = ? '
                                      "ORDER BY fid", (group,))
                self.assertEqual(rows.fetchall(), expected)
                self.assertEqual(self.content(copy.record, temporary / "V01.r1.gpkg", layer),
                                 copy.record.content_sha256)
        (identifiers,) = snapshot.execute(
            "SELECT count(DISTINCT identifier) = count(*) FROM gpkg_contents").fetchone()
        self.assertEqual(identifiers, 1)
        body = json.loads((temporary / copy_mod.MANIFEST_NAME).read_bytes())
        self.assertEqual(body["accepted"], accepted)
        self.assertEqual(accepted["reason"], "Se entrega con el banco anterior")
        self.assertEqual([(entry["item_kind"], entry["item_uid"], entry["state"])
                          for entry in accepted["items"]],
                         [(str(entry.item_kind), entry.item_uid, str(entry.state))
                          for entry in plan.accept])
        entries = {entry["uid"]: entry for entry in body["datasets"]}
        self.assertEqual(entries[second.uid]["layer"], f"{shared}_{second.uid[:8]}")
        self.assertEqual(entries[first.uid]["selector"], {"column": "grp", "equals": "a"})
        self.assertIsNone(copy_mod.acceptance(dataclasses.replace(plan, accept=()),
                                              reason="Nada"))
        snapshot.close()
        copy_mod.discard(temporary)
        self.assertEqual(self.snapshots(), [])
        self.assertIsNotNone(result)

    def bench(self, value: float) -> None:
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source="Plan de labores (prueba)",
            decided_by="Samuel (IMGA)", reason="Banco de la prueba", version="V01"))


class ReferencedTest(FreezeCopyCase):
    def test_already_copied_is_referenced_and_empty_revision(self) -> None:
        """RF-009-07, D-28, D-41, RNF-009-06 (plan A6, §5.2.5): tras copiar V01.r1 (y
        anotarla congelada), la copia de V02 copia solo lo suyo (rejilla, malla y sus dos
        tablas) y referencia en el manifiesto los 5 datos del proyecto ya copiados en V01.r1,
        sin copiarlos; y V01.r2, que no cambia nada, se congela con su manifiesto solo: ningún
        GeoPackage ni fichero de datos, todo referenciado a V01.r1."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        first = self.plan()
        result, _progress, temporary = self.finished(first)
        copy_mod.rename_snapshot(temporary, self.root / "snapshots" / "V01.r1")
        self.freeze(self.v1, [
            (self.record(item.item_uid), str(item.part), item.snapshot_path, item.snapshot_layer)
            for item in result.items
            if item.item_kind is ItemKind.DATASET and item.snapshot_path is not None])

        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=12.0, source="Plan de labores (prueba)",
            decided_by="Samuel (IMGA)", reason="Banco de V02", version="V02"))
        self.demo.pit(self.project, "V02")
        self.demo.pit_stockpiles(self.project, "V02")
        second = self.plan("V02")
        upstream = {self.record(name).uid for name in UPSTREAM_TABLES}
        self.assertEqual({item.item_uid for item in second.referenced}, upstream)
        result, _progress, temporary = self.finished(second)
        listed = sorted(path.relative_to(temporary).as_posix()
                        for path in temporary.rglob("*") if path.is_file())
        own = sorted(copy.record.locator for copy in second.to_copy
                     if str(copy.record.store) != "gpkg")
        self.assertEqual(listed, sorted([*own, "V02.r1.gpkg", "manifest.json"]))
        snapshot = sqlite3.connect(f"{(temporary / 'V02.r1.gpkg').as_uri()}?mode=ro", uri=True)
        self.addCleanup(snapshot.close)
        self.assertEqual({str(name) for (name,) in snapshot.execute(
            "SELECT table_name FROM gpkg_contents")},
            {self.record(name, "V02").locator
             for name in (vdemo.PIT_BENCHES, vdemo.PIT_STOCKPILES_TABLE)})
        body = model.expand_manifest(json.loads((temporary / copy_mod.MANIFEST_NAME).read_bytes()))
        entries = {entry["uid"]: entry for entry in body["datasets"]}
        for uid in upstream:
            self.assertEqual((entries[uid]["location"], entries[uid]["path"],
                              entries[uid]["layer"]),
                             ("other", "snapshots/V01.r1/V01.r1.gpkg", self.record(uid).locator))
        snapshot.close()
        copy_mod.discard(temporary)
        self.assertEqual(self.snapshots(), ["V01.r1"])

        empty = self.plan()
        self.assertEqual((empty.label, empty.to_copy), ("V01.r2", ()))
        before = self.state()
        result, progress, temporary = self.finished(empty)
        self.assertEqual([path.name for path in temporary.iterdir()], [copy_mod.MANIFEST_NAME])
        self.assertEqual((result.files, result.copied_bytes), ((), 0))
        body = model.expand_manifest(json.loads((temporary / copy_mod.MANIFEST_NAME).read_bytes()))
        self.assertEqual(body["files"], [])
        self.assertEqual({entry["location"] for entry in body["datasets"]
                          if entry["part"] != "immutable"}, {"other"})
        self.assertNotIn("tablas", {step.phase for step in progress})
        self.assertEqual(self.state()[:3], before[:3])


class CancelTest(FreezeCopyCase):
    def test_esc_in_each_phase(self) -> None:
        """RF-009-07, D-11, RNF-009-02 (plan A6 (5)): cerrar los pasos (Esc) en cada fase
        (comprobando el espacio, a mitad de un fichero, comprobando su contenido, a mitad de
        las filas de una tabla y antes del manifiesto) borra la temporal, el GeoPackage de la
        caché y la caché que creó: nada queda, nada escrito en la base. Tras el último
        paso (el del resultado) la temporal es de quien llama, que la renombra o la descarta."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        plan = self.plan()
        before = self.state()
        stops = (("espacio", 1), ("copia", 1), ("copia", 3), ("comprobación", 1),
                 ("tablas", 1), ("tablas", 4), ("manifiesto", 1))
        with mock.patch.object(copy_mod, "CHUNK_BYTES", 4096), \
                mock.patch.object(copy_mod, "ROWS_PER_STEP", 1):
            for phase, nth in stops:
                seen: list[str] = []

                def stop(step: Any, phase: str = phase, nth: int = nth,
                         seen: list[str] = seen) -> bool:
                    seen.append(step.phase)
                    return seen.count(phase) == nth

                with self.subTest(phase=phase, nth=nth):
                    progress, temporary = self.copy(plan, stop=stop)
                    self.assertEqual((progress[-1].phase, seen.count(phase)), (phase, nth))
                    self.assertIsNone(progress[-1].result)
                    self.assertNothingLeft(before, temporary)
        result, _progress, temporary = self.finished(plan)
        self.assertTrue((temporary / copy_mod.MANIFEST_NAME).is_file())
        copy_mod.discard(temporary)
        self.assertNothingLeft(before, temporary)


class ChangedTest(FreezeCopyCase):
    def setUp(self) -> None:
        super().setUp()
        self.demo.pit(self.project, "V01")
        self.plan_v01 = self.plan()
        self.before = self.state()

    def test_table_changed_by_another_connection(self) -> None:
        """RF-009-07 (plan A6 (2) y (5)): otra conexión (como QGIS) cambia la tabla de bancos
        mientras se copian sus filas: «cambió mientras se congelaba», la temporal y el
        GeoPackage de la caché, borrados; Geoblender no escribe nada (solo cambió lo de la otra
        conexión)."""
        benches = self.record(vdemo.PIT_BENCHES, "V01")

        def stop(step: Any) -> bool:
            if (step.phase == "tablas" and f"«{benches.locator}»" in step.message
                    and not stop.done):  # type: ignore[attr-defined]
                other = sqlite3.connect(str(self.project.database_path))
                try:
                    other.execute(f'UPDATE "{benches.locator}" SET area_m2 = area_m2 + 1 '
                                  "WHERE bench = 3")
                    other.commit()
                finally:
                    other.close()
                stop.done = True  # type: ignore[attr-defined]
            return False

        stop.done = False  # type: ignore[attr-defined]
        with mock.patch.object(copy_mod, "ROWS_PER_STEP", 1):
            error = self.assertRefused("core.version_freeze_changed",
                                       lambda: self.copy(self.plan_v01, stop=stop))
        self.assertTrue(stop.done)  # type: ignore[attr-defined]
        self.assertEqual(error.values["dataset"], vdemo.PIT_BENCHES)
        self.assertEqual(error.values["revision"], "V01.r1")
        files, counter, cached, snapshots = self.state()
        self.assertEqual((files, cached, snapshots), (self.before[0], *self.before[2:]))
        self.assertEqual(counter, self.before[1] + 1)
        self.assertEqual(self.query("SELECT count(*) FROM gb_revision_item"), [(0,)])

    def test_file_rewritten_while_copying(self) -> None:
        """RF-009-07 (plan A6 (1) y (5)): la rejilla cambia (otro tamaño y otra fecha)
        mientras se copia: «cambió mientras se congelaba»; no queda nada."""
        grid = self.record(vdemo.PIT_GRID, "V01")
        source = self.root / grid.locator

        def stop(step: Any) -> bool:
            if step.phase == "copia" and not stop.done:  # type: ignore[attr-defined]
                with source.open("ab") as stream:
                    stream.write(b"\0")
                stop.done = True  # type: ignore[attr-defined]
            return False

        stop.done = False  # type: ignore[attr-defined]
        with mock.patch.object(copy_mod, "CHUNK_BYTES", 1024):
            error = self.assertRefused("core.version_freeze_changed",
                                       lambda: self.copy(self.plan_v01, stop=stop))
        self.assertEqual(error.values["dataset"], vdemo.PIT_GRID)
        self.assertEqual(self.state()[1:], self.before[1:])

    def test_copy_without_its_registered_content(self) -> None:
        """RF-009-07, D-30 (plan A6 (1)): si el hash de contenido de la copia no es el
        registrado, se cancela todo («no tiene su contenido registrado») sin dejar nada."""
        changed = tuple(
            dataclasses.replace(copy, record=dataclasses.replace(
                copy.record, content_sha256="0" * 64))
            if copy.record.name == vdemo.PIT_MESH else copy
            for copy in self.plan_v01.to_copy)
        plan = dataclasses.replace(self.plan_v01, to_copy=changed)
        error = self.assertRefused("core.version_freeze_mismatch", lambda: self.copy(plan))
        self.assertEqual(error.values["dataset"], vdemo.PIT_MESH)
        self.assertEqual(self.state(), self.before)


class SpaceAndLeftoversTest(FreezeCopyCase):
    def test_no_space_and_leftovers(self) -> None:
        """RF-009-07 (plan A5 (5), A6 (4)): sin espacio para lo que se copia más un 10 % (en
        ``snapshots/`` y, para el GeoPackage, en la caché; en el mismo disco, las dos cosas), no
        se crea nada y se dice cuánto hace falta y cuánto queda; con justo eso, se copia. Al
        renombrar, unos restos de otra congelación con el nombre de la revisión no se
        sustituyen: «Hay restos de una congelación anterior en «snapshots/V01.r1»…»; la
        temporal se descarta después."""
        self.demo.pit(self.project, "V01")
        plan = self.plan()
        self.assertGreater(plan.cache_needed, 0)
        before = self.state()
        needed = plan.space_needed + plan.cache_needed

        def disk(free: int) -> Callable[[Path], Any]:
            return lambda _path: types.SimpleNamespace(free=free)

        error = self.assertRefused("core.version_freeze_no_space",
                                   lambda: self.copy(plan, disk_usage=disk(needed - 1)))
        self.assertIn("quedan", str(error))
        self.assertEqual(self.state(), before)
        result, _progress, temporary = self.finished(plan, disk_usage=disk(needed))

        leftover = self.root / "snapshots" / "V01.r1"
        leftover.mkdir()  # unos restos con el nombre de la revisión
        (leftover / "manifest.json").write_bytes(b"{}")
        error = self.assertRefused(
            "core.version_freeze_leftover",
            lambda: copy_mod.rename_snapshot(temporary, leftover))
        self.assertIn("snapshots/V01.r1", str(error))
        self.assertTrue((temporary / copy_mod.MANIFEST_NAME).is_file())
        self.assertEqual([path.name for path in leftover.iterdir()], ["manifest.json"])
        copy_mod.discard(temporary)
        self.assertEqual(self.snapshots(), ["V01.r1"])
        self.assertIsNotNone(result)

        # Una carpeta que ya tiene el nombre de la temporal no es suya: no la toca.
        taken = copy_mod.temporary_path(self.root, plan.label)
        taken.mkdir()
        (taken / "ajeno.txt").write_bytes(b"x")
        steps = copy_mod.copy_steps(self.project, plan, taken, self.cache(), budget_s=TINY)
        self.assertRefused("core.version_freeze_failed", lambda: list(steps))
        self.assertEqual([path.name for path in taken.iterdir()], ["ajeno.txt"])


# --- Congelar: el plan, la copia y la confirmación (T13) -------------------------------------


def _folder_size(root: Path) -> int:
    """Lo que ocupa la carpeta del proyecto sin su caché (RNF-009-06)."""
    total = 0
    for folder, dirs, names in os.walk(root):
        if Path(folder) == Path(root) and "cache" in dirs:
            dirs.remove("cache")
        total += sum(os.stat(os.path.join(folder, name)).st_size for name in names)
    return total


def _row(item: Any) -> tuple[Any, ...]:
    """Un ``RevisionItem`` como su fila de ``gb_revision_item`` (sin ``fid``)."""
    return (item.revision_uid, str(item.item_kind), item.item_uid, str(item.part), item.item_rev,
            item.content_sha256, int(item.copied), item.snapshot_path, item.snapshot_layer,
            item.file_sha256, item.file_size, str(item.state))


class FreezeStepsCase(FreezeCopyCase):
    """Ayudas para congelar con ``freeze_steps`` (el plan, la copia y la confirmación)."""

    def freeze_steps(self, version: str, reason: str = "Siguiente revisión", *,
                     at: dict[str, Callable[[], Any]] | None = None,
                     **kw: Any) -> tuple[Any, list[Any]]:
        """Congela la revisión abierta de ``version`` (un minuto después) hasta el final: su
        ``FreezeOutcome`` y los pasos. ``at``: lo que se hace, una vez, al ver el primer paso de
        cada fase, con los pasos parados (otra operación, el barrido de restos)."""
        self.tick()
        steps = freeze.freeze_steps(self.project, version, reason=reason, **kw)
        pending = dict(at or {})
        seen: list[Any] = []
        try:
            for step in steps:
                seen.append(step)
                work = pending.pop(step.phase, None)
                if work is not None:
                    work()
        finally:
            steps.close()
        self.assertEqual([step.result is not None for step in seen].count(True), 1)
        self.assertIsNotNone(seen[-1].result)
        return seen[-1].result, seen

    def revision(self, uid: str) -> Any:
        return self.read(lambda conn: versions_read.revision(conn, uid))

    def opened(self, version: Any) -> Any:
        return self.read(lambda conn: versions_read.open_revision(conn, version.uid))

    def items(self, revision_uid: str) -> list[tuple[Any, ...]]:
        """Las filas de ``gb_revision_item`` de una revisión, sin ``fid``, en su orden."""
        return self.query(
            "SELECT revision_uid, item_kind, item_uid, part, item_rev, content_sha256, copied, "
            "snapshot_path, snapshot_layer, file_sha256, file_size, state FROM gb_revision_item "
            "WHERE revision_uid = ? ORDER BY fid", (revision_uid,))

    def events(self, kind: Any) -> list[Any]:
        return self.read(lambda conn: events_mod.read_events(conn, kind))

    def header(self) -> dict[str, Any]:
        """La cabecera del proyecto (``manifest.json``) tal como está en el disco."""
        return json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def bench(self, value: float) -> None:
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source="Plan de labores (prueba)",
            decided_by="Samuel (IMGA)", reason="Banco de la prueba", version="V01"))


def _entry(revision: Any, label: str) -> dict[str, Any]:
    """La línea de una revisión congelada en el inventario de la cabecera (§5.2.4)."""
    return {"revision": label, "revision_uid": revision.uid,
            "manifest": f"snapshots/{label}/manifest.json", "sha256": revision.snapshot_sha256,
            "frozen_at": revision.closed_at}


class ConfirmTest(FreezeStepsCase):
    def test_frozen_and_next_opened_in_one_transaction(self) -> None:
        """RF-009-06, RF-009-07, D-28, D-41, RNF-009-06 (plan A7, §5.2.4): con el hueco, su
        volumen y los acopios en V01, ``freeze_steps`` copia la instantánea y, en **una**
        transacción (la base cambia una vez), deja V01.r1 congelada con sus elementos (los del
        plan, con la huella y el tamaño de su copia), la huella de su manifiesto, sus bytes, lo
        aceptado (nada) y la versión de Geoblender, quién y cuándo, y V01.r2 abierta con el motivo
        dado; los eventos ``revision_frozen`` y ``revision_opened``; la carpeta con su nombre
        (ninguna temporal); la cabecera con su inventario; las cifras vigentes de V01, ya las
        congeladas (D-9); el progreso por fases. V01.r2, sin cambios, se congela con su
        manifiesto solo (todo referenciado). El proyecto crece como mucho lo copiado + 1 MB
        (RNF-009-06, preliminar)."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_volume(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        plan = self.plan()
        self.assertFalse(plan.accept or plan.blockers)
        self.assertTrue(plan.to_copy and plan.referenced == ())
        counter, size = self.change_counter(), _folder_size(self.root)
        outcome, progress = self.freeze_steps("V01", "Entrega al cliente")

        self.assertEqual(self.change_counter(), counter + 1)
        self.assertEqual(self.snapshots(), ["V01.r1"])
        self.assertEqual(freezing.freezing_paths(self.project), frozenset())
        if self.cache().is_dir():
            self.assertEqual([path.name for path in self.cache().iterdir()
                              if freeze.FREEZING_MARK in path.name], [])
        folder = self.root / "snapshots" / "V01.r1"
        raw = (folder / copy_mod.MANIFEST_NAME).read_bytes()
        body = json.loads(raw)
        files = {item["path"]: item for item in body["files"]}
        frozen = self.revision(plan.revision.uid)
        self.assertEqual(
            (frozen.state, frozen.snapshot_dir, frozen.snapshot_sha256, frozen.snapshot_bytes,
             frozen.geoblender_version, frozen.accepted, frozen.closed_at, frozen.closed_by,
             frozen.altered_at),
            (model.RevisionState.FROZEN, "snapshots/V01.r1", hashlib.sha256(raw).hexdigest(),
             sum(item["size"] for item in body["files"]), version_mod.geoblender_version(), None,
             self.now(), fixtures.USER, None))
        self.assertEqual((body["revision_uid"], body["frozen_at"], body["frozen_by"]),
                         (frozen.uid, frozen.closed_at, frozen.closed_by))
        expected = []
        for item in plan.items:
            path = item.snapshot_path or ""
            if path.startswith("snapshots/V01.r1/"):
                found = files[path.removeprefix("snapshots/V01.r1/")]
                item = dataclasses.replace(item, file_sha256=found["sha256"],
                                           file_size=found["size"])
            expected.append(_row(item))
        self.assertEqual(self.items(frozen.uid), expected)
        self.assertTrue(all(row[9] and row[10] for row in expected if row[6]))

        opened = self.opened(self.v1)
        self.assertEqual((opened.number, opened.state, opened.reason, opened.created_at,
                          opened.created_by),
                         (2, model.RevisionState.OPEN, "Entrega al cliente", self.now(),
                          fixtures.USER))
        self.assertEqual((outcome.frozen, outcome.opened, outcome.cancelled, outcome.warnings),
                         (frozen, opened, False, ()))
        self.assertEqual(outcome.files, tuple(copy_mod.SnapshotFile(**item)
                                              for item in body["files"]))
        self.assertEqual(outcome.copied_bytes, frozen.snapshot_bytes)
        self.assertEqual(outcome.referenced, ())
        (event,) = self.events(EVENT.REVISION_FROZEN)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.user_host),
                         ("revision", frozen.uid, self.now(), fixtures.USER))
        self.assertEqual({key: event.data[key] for key in (
            "version", "revision", "snapshot_dir", "snapshot_sha256", "snapshot_bytes", "items")},
            {"version": "V01", "revision": "V01.r1", "snapshot_dir": "snapshots/V01.r1",
             "snapshot_sha256": frozen.snapshot_sha256, "snapshot_bytes": frozen.snapshot_bytes,
             "items": len(plan.items)})
        self.assertEqual(sorted(entry["path"] for entry in event.data["copied"]),
                         sorted(files))
        (event,) = self.events(EVENT.REVISION_OPENED)
        self.assertEqual((event.entity_uid, event.data["revision"], event.data["reason"]),
                         (opened.uid, "V01.r2", "Entrega al cliente"))
        self.assertEqual(self.header()["inventory"], [_entry(frozen, "V01.r1")])
        figures = self.read(lambda conn: versions_read.version_figures(conn, "V01"))
        self.assertEqual([figure.key for figure in figures], [vdemo.PIT_VOLUME_FIGURE])

        phases = [step.phase for step in progress]
        every = [*copy_mod.PHASES, freeze.CONFIRM_PHASE]
        # Con el presupuesto por defecto, qué fases dan un paso depende del tiempo; y la
        # comprobación es la de cada fichero, tras su copia, y la de las tablas, tras «tablas»
        # (009/T14: con la máquina cargada salió «tablas» antes que la primera comprobación).
        ranks = [every.index(phase) for phase in phases if phase != "comprobación"]
        self.assertEqual(ranks, sorted(ranks))
        self.assertLessEqual(set(phases), set(every))
        self.assertEqual((phases[0], phases[-1]), (every[0], every[-1]))
        done = [step.done for step in progress]
        self.assertEqual(done, sorted(done))
        self.assertEqual((done[-1], progress[-1].phase), (progress[-1].total,
                                                          freeze.CONFIRM_PHASE))
        self.assertIn("V01.r1 congelada", progress[-1].message)
        self.assertIn("V01.r2 abierta", progress[-1].message)
        self.assertLessEqual(_folder_size(self.root) - size, outcome.copied_bytes + MB)

        # V01.r2, sin cambios: nada copiado, todo referenciado a V01.r1 (D-28, RNF-009-06).
        size = _folder_size(self.root)
        again, _progress = self.freeze_steps("V01", "Sin cambios")
        self.assertEqual((again.copied_bytes, again.files, again.frozen.snapshot_bytes),
                         (0, (), 0))
        self.assertEqual([path.name for path in (self.root / "snapshots" / "V01.r2").iterdir()],
                         [copy_mod.MANIFEST_NAME])
        self.assertEqual({item.item_uid for item in again.referenced},
                         {item.item_uid for item in plan.items
                          if item.item_kind is ItemKind.DATASET and item.copied})
        self.assertEqual({row[1:3] for row in self.items(again.frozen.uid)},
                         {row[1:3] for row in expected})
        self.assertLessEqual(_folder_size(self.root) - size, MB)
        self.assertEqual(self.header()["inventory"],
                         [_entry(frozen, "V01.r1"), _entry(again.frozen, "V01.r2")])
        self.assertEqual(self.opened(self.v1).number, 3)


class AcceptTest(FreezeStepsCase):
    def test_acceptance_and_what_prevents_it(self) -> None:
        """RF-009-06, RF-009-08 (plan A5 (1) y (3), A7): sin motivo no se congela; con algo
        que aceptar (el banco de V01 cambiado: lo del hueco, obsoleto) no se congela sin la
        aceptación del usuario de **todo** lo que lo pide (nombrado en el rechazo), sin escribir
        nada; con ella, lo aceptado queda en la revisión y en su manifiesto con su motivo, y
        cada elemento con su estado al congelarse; en solo lectura, tampoco."""
        self.demo.pit(self.project, "V01")
        self.bench(12.0)
        plan = self.plan()
        self.assertTrue(plan.accept)
        before = self.state()
        for reason in ("", "   "):
            with self.subTest(reason=reason):
                self.assertRefused("core.version_freeze_reason", lambda: freeze.freeze_steps(
                    self.project, "V01", reason=reason))
        error = self.assertRefused("core.version_freeze_accept", lambda: freeze.freeze_steps(
            self.project, "V01", reason="Entrega"))
        for entry in plan.accept:
            self.assertIn(entry.name, str(error))
        whole = freeze.Acceptance.of(plan)
        self.assertEqual(whole.items, frozenset((str(entry.item_kind), entry.item_uid)
                                                for entry in plan.accept))
        partial = freeze.Acceptance(frozenset(sorted(whole.items)[1:]))
        self.assertRefused("core.version_freeze_accept", lambda: freeze.freeze_steps(
            self.project, "V01", reason="Entrega", accepted=partial))
        self.assertEqual(self.state(), before)

        reason = "Se entrega con el banco anterior"
        outcome, _progress = self.freeze_steps("V01", reason, accepted=whole)
        accepted = copy_mod.acceptance(plan, reason=reason)
        self.assertEqual(json.loads(str(outcome.frozen.accepted)), accepted)
        body = json.loads((self.root / "snapshots" / "V01.r1" / copy_mod.MANIFEST_NAME)
                          .read_bytes())
        self.assertEqual(body["accepted"], accepted)
        states = {(row[1], row[2]): row[11] for row in self.items(outcome.frozen.uid)}
        self.assertEqual(states, {(str(item.item_kind), item.item_uid): str(item.state)
                                  for item in plan.items})
        self.assertIn(str(model.ItemState.STALE), states.values())
        self.assertTrue(self.events(EVENT.REVISION_FROZEN)[0].data["accepted"])

        self.project.set_read_only(project_model.ReadOnlyCode.REQUESTED, "a petición (prueba)")
        self.assertRefused("core.version_freeze_read_only", lambda: freeze.freeze_steps(
            self.project, "V01", reason="Otra"))


def _scalars(value: Any) -> Iterator[Any]:
    """Todos los valores de un JSON que no son listas ni objetos."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _scalars(item)
    elif isinstance(value, list):
        for item in value:
            yield from _scalars(item)
    else:
        yield value


class CompactTest(FreezeStepsCase):
    def test_unchanged_revision_event_and_manifest(self) -> None:
        """RNF-009-06, RF-009-07, D-28 (plan §5.2.5, §5.2.6, D-39; T33): congelada V01.r1 (el
        hueco y los acopios, con la cadena de la 008 aguas arriba), V01.r2 sin cambios lo
        referencia todo. Su evento ``revision_frozen`` no repite la lista de lo referenciado
        (está en ``gb_revision_item``, con su ruta y su capa): cuántos, en su texto. Su
        manifiesto, compacto: ningún nulo ni nada de lo que vale lo de por defecto (el estado
        «al día», lo producido, el selector, el lector y el normalizador de una capa del
        GeoPackage, ``location`` «other», lo aceptado), la ruta de cada fichero de V01.r1 una
        sola vez (``referenced``) y cada dato con su índice; entero (``expand_manifest``),
        cada dato dice lo que anota ``gb_revision_item`` (la ruta y la capa en V01.r1, o lo
        inmutable en el proyecto), y vuelve a dar el mismo compacto."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        first, _progress = self.freeze_steps("V01", "Entrega")
        again, _progress = self.freeze_steps("V01", "Sin cambios")
        self.assertEqual(again.copied_bytes, 0)
        rows = {row[2]: row for row in self.items(again.frozen.uid) if row[1] == "dataset"}
        referenced = {uid: row for uid, row in rows.items() if row[7] is not None}
        self.assertEqual(set(referenced), {item.item_uid for item in again.referenced})
        self.assertTrue(referenced and set(referenced) < set(rows))

        events = self.events(EVENT.REVISION_FROZEN)
        self.assertEqual([event.entity_uid for event in events],
                         [first.frozen.uid, again.frozen.uid])
        for event in events:
            self.assertEqual(set(event.data), {
                "version", "revision", "snapshot_dir", "snapshot_sha256", "snapshot_bytes",
                "geoblender_version", "items", "copied", "accepted"})
        self.assertEqual((events[1].data["items"], events[1].data["copied"]),
                         (len(self.items(again.frozen.uid)), []))
        self.assertIn(f", {len(referenced)} contenido(s) ya congelado(s), referenciado(s),",
                      events[1].message)

        raw = (self.root / "snapshots" / "V01.r2" / copy_mod.MANIFEST_NAME).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), again.frozen.snapshot_sha256)
        body = json.loads(raw)
        self.assertEqual(raw, hashing.canonical_json(body))
        self.assertNotIn(None, list(_scalars(body)))
        for text in (b'"state":"current"', b'"part":"produced"', b'"selector"',
                     b'"reader":"core.gpkg_layer@1"', b'"normalizer":"gbch/1"', b'"store":"gpkg"',
                     b'"location":"other"', b'"accepted"', b'"files"', b'"originals":[]'):
            self.assertNotIn(text, raw)
        paths = sorted({str(row[7]) for row in referenced.values()})
        self.assertEqual(sorted(body["referenced"]), paths)
        for path in paths:
            self.assertEqual(raw.count(f'"{path}"'.encode()), 1, path)

        expanded = model.expand_manifest(body)
        self.assertEqual(model.compact_manifest(expanded), body)
        self.assertLess(len(raw), len(hashing.canonical_json(expanded)))
        self.assertEqual([entry["uid"] for entry in expanded["datasets"]], list(rows))
        for entry in expanded["datasets"]:
            row = rows[entry["uid"]]
            record = self.record(entry["uid"])
            with self.subTest(dataset=record.name):
                self.assertEqual(
                    {key: entry[key] for key in ("name", "kind", "store", "reader", "normalizer",
                                                 "selector", "content_sha256", "part", "state")},
                    {"name": record.name, "kind": record.kind, "store": str(record.store),
                     "reader": record.reader, "normalizer": record.normalizer,
                     "selector": record.selector, "content_sha256": row[5], "part": row[3],
                     "state": row[11]})
                if row[7] is None:
                    self.assertEqual((entry["part"], entry["location"], entry["layer"]),
                                     ("immutable", "project", record.locator))
                else:
                    self.assertEqual((entry["location"], entry["path"], entry["layer"]),
                                     ("other", row[7], row[8]))


class EmptyAndHeaderTest(FreezeStepsCase):
    def test_empty_revision_and_header_regenerated_at_opening(self) -> None:
        """D-41, RF-009-06, RF-009-07 (plan A7, §5.2.4): V02, sin nada, se congela con su
        manifiesto solo (ningún elemento, 0 bytes) y abre V02.r2. Si la cabecera no se puede
        escribir tras confirmar, la revisión queda congelada (la base manda) con un aviso; al
        volver a abrir el proyecto en escritura, la cabecera se regenera con su inventario
        (aviso y evento ``manifest_rewritten`` con «inventory»)."""
        failed = errors.ProjectError("core.manifest_write_failed", "no se ha podido escribir "
                                     "(prueba)", obj="Proyecto", field="manifest.json")
        with mock.patch.object(session_mod, "write_manifest", side_effect=failed), \
                self.assertLogs(events_mod.LOGGER, "WARNING") as logged:
            outcome, _progress = self.freeze_steps("V02", "Primera entrega")
            self.assertEqual(len(self.project.close()), 1)
        self.assertTrue(any("V02.r1" in line for line in logged.output))
        frozen = outcome.frozen
        self.assertEqual((frozen.state, frozen.snapshot_bytes, outcome.files),
                         (model.RevisionState.FROZEN, 0, ()))
        self.assertEqual(self.items(frozen.uid), [])
        self.assertEqual([path.name for path in (self.root / "snapshots" / "V02.r1").iterdir()],
                         [copy_mod.MANIFEST_NAME])
        self.assertEqual((outcome.opened.number, outcome.opened.reason), (2, "Primera entrega"))
        (warning,) = outcome.warnings
        self.assertIn("manifest.json", warning)
        self.assertEqual(self.header()["inventory"], [])

        reopened = open_mod.open_project(self.root, fixtures.SESSION, self.userdata,
                                         clock=self.clock, pid_alive=fixtures.PIDS)
        self.addCleanup(reopened.project.close)
        self.assertTrue(any("inventory" in text for text in reopened.warnings))
        self.assertEqual(self.header()["inventory"], [_entry(frozen, "V02.r1")])
        self.assertEqual(reopened.project.manifest.inventory, (_entry(frozen, "V02.r1"),))
        with reopened.project.read() as conn:
            (event,) = events_mod.read_events(conn, EVENT.MANIFEST_REWRITTEN)
        self.assertEqual(event.data["fields"], ["inventory"])


class ConcurrentTest(FreezeStepsCase):
    def test_operation_finished_meanwhile(self) -> None:
        """D-40, RF-009-06, RF-009-07 (plan A7): mientras se congela, una operación de V01 que
        se registra (``demo.pit_volume``) o una del proyecto que cambia algo congelado
        (``demo.digitize`` con otros tonelajes: los bancos, aguas arriba) cancelan la
        congelación al confirmar, sin dejar nada (ni la temporal, ni filas: la revisión sigue
        abierta); una del proyecto que no cambia nada congelado (``demo.balance``) no la
        impide."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        open_uid = self.opened(self.v1).uid
        benches = [(name, 2 * tonnes) for name, tonnes in demo_support.DEFAULT_BENCHES]
        cases = (
            ("core.version_freeze_operation", vdemo.PIT_VOLUME,
             lambda: self.demo.pit_volume(self.project, "V01")),
            ("core.version_freeze_changed", demo_support.BENCHES_TABLE,
             lambda: self.demo.digitize(self.project, benches=benches)),
        )
        for code, name, work in cases:
            with self.subTest(code=code):
                error = self.assertRefused(code, lambda work=work: self.freeze_steps(
                    "V01", "Entrega", at={freeze.CONFIRM_PHASE: work}))
                self.assertIn(f"«{name}»", str(error))
                self.assertEqual(self.snapshots(), [])
                self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?",
                                            (open_uid,)), [("open",)])
                self.assertEqual(self.query("SELECT count(*) FROM gb_revision_item"), [(0,)])
                self.assertEqual(freezing.freezing_paths(self.project), frozenset())
        plan = self.plan()  # los bancos cambiados dejan obsoleto lo de aguas arriba
        outcome, _progress = self.freeze_steps(
            "V01", "Entrega", accepted=freeze.Acceptance.of(plan),
            at={freeze.CONFIRM_PHASE: lambda: self.demo.balance(self.project, loose_m3=1300.0)})
        self.assertEqual((outcome.frozen.uid, outcome.frozen.state),
                         (open_uid, model.RevisionState.FROZEN))
        self.assertEqual(self.snapshots(), ["V01.r1"])


class LeftoversTest(FreezeStepsCase):
    def put(self, rel: str, data: bytes) -> Path:
        """Escribe ``rel`` con la fecha de hace una hora (lo que deja un cierre a medias)."""
        path = self.root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        old = time.time_ns() - HOUR_NS
        os.utime(path, ns=(old, old))
        return path

    def sweep(self, **kw: Any) -> Any:
        """El barrido de restos de la comprobación de apertura, entero; su resultado."""
        return list(orphans.orphan_steps(self.project, write=True, **kw))[-1].result

    def test_half_closed_freeze_goes_to_orphans(self) -> None:
        """RF-009-07, RF-008-22, D-11 (plan A6 (5)): un cierre a medias —la temporal de una
        congelación (con sus ficheros o vacía) y una carpeta ya renombrada sin su revisión
        congelada— impide congelar («ya se está congelando») hasta que el barrido de restos de
        la apertura la aparta, entera y sin borrar nada, a ``orphans/<fecha>_<sesión>/snapshots/``;
        la instantánea de una revisión congelada y lo que no lleva nombre de instantánea no se
        tocan; después se congela como siempre."""
        first, _progress = self.freeze_steps("V02", "Primera")
        leftovers = {
            "snapshots/V01.r1.congelando-0a1b2c3d/manifest.json": b"{}",
            "snapshots/V01.r1.congelando-0a1b2c3d/rasters/demo_pit_grid_v01.tif": b"tif",
            "snapshots/V01.r1/manifest.json": b'{"revision": "V01.r1"}',
            "snapshots/notas/leeme.txt": b"nota",
        }
        for rel, data in leftovers.items():
            self.put(rel, data)
        (self.root / "snapshots" / "V01.r2.congelando-99999999").mkdir()
        error = self.assertRefused("core.version_freeze_in_progress",
                                   lambda: freeze.freeze_steps(self.project, "V01",
                                                               reason="Otra"))
        self.assertIn("V01.r1.congelando-0a1b2c3d", str(error))

        found = self.sweep()
        moved = {item.path: (item.folder, item.moved_to) for item in found.moved}
        names = ("V01.r1", "V01.r1.congelando-0a1b2c3d", "V01.r2.congelando-99999999")
        self.assertEqual(moved, {f"snapshots/{name}": (True, f"{found.folder}/snapshots/{name}")
                                 for name in names})
        for rel, data in leftovers.items():
            where = rel if rel.startswith("snapshots/notas/") else f"{found.folder}/{rel}"
            self.assertEqual(self.root.joinpath(*where.split("/")).read_bytes(), data)
        self.assertTrue((self.root / found.folder / "snapshots" / names[2]).is_dir())
        self.assertEqual(self.snapshots(), ["V02.r1", "notas"])
        self.assertEqual(json.loads((self.root / "snapshots" / "V02.r1" / copy_mod.MANIFEST_NAME)
                                    .read_bytes())["revision_uid"], first.frozen.uid)
        (event,) = self.events(EVENT.ORPHANS_MOVED)
        self.assertEqual(sorted(path for path, _target in event.data["moved"]),
                         sorted(moved))

        outcome, _progress = self.freeze_steps("V01", "Tras apartar los restos")
        self.assertEqual(outcome.frozen.snapshot_dir, "snapshots/V01.r1")
        self.assertEqual(self.snapshots(), ["V01.r1", "V02.r1", "notas"])

    def test_this_sessions_temporary_is_not_set_aside(self) -> None:
        """RF-009-07, D-40 (plan A6): la temporal de la congelación en curso de esta sesión no
        se aparta aunque el barrido de restos corra a mitad de la copia (tampoco por su fecha:
        se barre como si hubiera empezado después); Esc la borra; ``cancelled`` cancela sin
        dejar nada; y la congelación que termina deja la instantánea, que el barrido ya no
        toca."""
        self.demo.pit(self.project, "V01")
        later = time.time_ns() + HOUR_NS
        before = self.state()
        steps = freeze.freeze_steps(self.project, "V01", reason="Entrega", budget_s=TINY)
        try:
            for step in steps:
                if step.phase == "comprobación":
                    break
            (temporary,) = freezing.freezing_paths(self.project)
            self.assertRegex(temporary.name, r"^V01\.r1\.congelando-[0-9a-f]{8}$")
            self.assertTrue(temporary.is_dir())
            self.assertEqual(self.sweep(started_at=later).orphans, ())
            self.assertTrue(temporary.is_dir())
        finally:
            steps.close()  # Esc
        self.assertFalse(temporary.exists())
        self.assertEqual(freezing.freezing_paths(self.project), frozenset())
        self.assertEqual(self.state(), before)

        stopped, _progress = self.freeze_steps("V01", "Entrega", cancelled=lambda: True)
        self.assertEqual((stopped.cancelled, stopped.frozen, stopped.opened), (True, None, None))
        self.assertEqual(self.state(), before)

        outcome, _progress = self.freeze_steps("V01", "Entrega")
        self.assertEqual(self.sweep(started_at=later).orphans, ())
        self.assertEqual(self.snapshots(), ["V01.r1"])
        self.assertEqual(outcome.frozen.state, model.RevisionState.FROZEN)


if __name__ == "__main__":
    unittest.main()

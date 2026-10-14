# SPDX-License-Identifier: GPL-3.0-or-later
"""Las fuentes de la topografía, intactas (spec 006, T25; RF-006-10; RF-008-14, RF-008-15,
RF-008-09; plan 006 §5.6.4 y §5.6.6; D9).

Los flujos completos de importación de la 006 sobre un proyecto sintético de esquema 2, con las
fuentes en ``entregas/``, fuera de él, una carpeta por fuente: el GeoTIFF, el ASC con su
``.prj``, el XYZ en malla y el CSV de los taludes pasan por su trabajo de la 004
(``gis_read_raster``, ``gis_import_points``: la fuente llega por ``--path`` y el trabajo la copia
a ``in/``), y su resultado se incorpora con ``ingest_job`` y ``gis.store.ResultWriter`` (la
entrada, lo importado y, del CSV, su original desde la copia verificada); las capas de un
GeoPackage, sin WAL y con un WAL pendiente de un escritor que terminó sin cerrar (``os._exit``,
como en la 002), se leen sobre su copia en la caché del proyecto (``gis.vector.copy_source``).
Después, la comprobación de las entradas de la 008: la de apertura (el prefiltro por tamaño y
fecha y, con el ``-wal``, el hash) y «Comprobar cambios en las entradas» (el hash de todas), en
el hilo y en el trabajo de hash ``core_content_hash`` (que copia el GeoPackage con su ``-wal``).

En cada paso, la carpeta de cada fuente queda con el mismo listado y, de cada fichero, el mismo
tamaño, la misma fecha y el mismo sha256 (``assert_source_untouched`` de la 008), sin ningún
``.aux.xml``, ``-wal``, ``-shm`` ni ``-journal`` nuevo (solo los que dejó el escritor del
GeoPackage en WAL).

Exportar sobre una entrada, en la carpeta de su fuente (fuera del proyecto) o en una carpeta de
solo lectura lo rechaza ``core.inputs.check_write_target`` de la 008 (``core.write_target_*``),
que sustituye a ``gis.export_over_input`` (plan §5.6.6): ese código sale del catálogo de ``gis``.
"""

from __future__ import annotations

import json
import shutil
import unittest
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched, is_auxiliary, source_state
from tests.support.repo import EXTENSION_DIR, ROOT
from tests.support.trees import age_folders
from tests.unit.gis.test_store import CRS, POINT_SETTINGS, VERTICAL, ImportCase
from tests.unit.gis.test_vector_read import WAL_LINES, _killed_writer

store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
gis_content = import_geoblender("gis.content")
gis_jobs = import_geoblender("gis.jobs")
messages = import_geoblender("gis.messages")
vector = import_geoblender("gis.vector")
points_mod = import_geoblender("gis.points")
geotiff = import_geoblender("gis.geotiff")
reader_mod = import_geoblender("gis.geotiff.reader")
core_gpkg = import_geoblender("core.gpkg")
inputs = import_geoblender("core.inputs")
input_model = import_geoblender("core.inputs.model")
input_check = import_geoblender("core.inputs.check")
checks = import_geoblender("core.provenance.checks")
operations = import_geoblender("core.provenance.operations")
prov_messages = import_geoblender("core.provenance.messages")
paths_mod = import_geoblender("core.paths")
readers = import_geoblender("core.content.readers")
encoder = import_geoblender("core.content.encoder")
content_hash = import_geoblender("jobs.content_hash")
job_paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
worker_api = import_geoblender("jobs.worker_api")

DATA = ROOT / "tests" / "data" / "gis"
DELIVERIES = {  # entregas/<carpeta de la fuente>/<fichero> ← tests/data/gis
    "mdt/f32_strip.tif": DATA / "geotiff" / "f32_strip.tif",
    "asc/corner.asc": DATA / "asc" / "corner.asc",
    "asc/corner.prj": DATA / "asc" / "corner.prj",
    "xyz/grid.xyz": DATA / "xyz" / "grid.xyz",
    "puntos/taludes.csv": DATA / "points" / "taludes.csv",
    "capas/capas.gpkg": DATA / "gpkg" / "capas.gpkg",
    "wal/capas.gpkg": DATA / "gpkg" / "capas.gpkg",  # con un WAL pendiente (setUp)
}
WAL_GPKG = "wal/capas.gpkg"
WAL_SIDES = ["wal/capas.gpkg-shm", "wal/capas.gpkg-wal"]  # los que dejó el escritor
CRS_JSON = {"epsg": 25830}
VERTICAL_JSON = {"epsg": 5782}
GRIDS = (  # nombre, lector, ficheros por papel, ajustes de lectura
    ("MDT Norte", gis_content.GEOTIFF, {"main": "mdt/f32_strip.tif"}, {}),
    ("MDT ASC", gis_content.ASC, {"main": "asc/corner.asc", "prj": "asc/corner.prj"}, {}),
    ("MDT XYZ", gis_content.XYZ_GRID, {"main": "xyz/grid.xyz"},
     {"separator": " ", "decimal": "."}),
)
LAYERS = (  # nombre, fichero, capa, papel
    ("Puntos GPKG", "capas/capas.gpkg", "puntos_z", "points"),
    ("Roturas WAL", WAL_GPKG, "roturas_z", "breaklines"),
)
NAMES = ("MDT Norte", "MDT ASC", "MDT XYZ", "Taludes", "Puntos GPKG", "Roturas WAL")
FOLDER_CODE = "core.write_target_source_folder"
SOURCE_CODE = "core.write_target_source"
READ_ONLY_CODE = "core.write_target_read_only"
OLD_CODE = "gis.export_over_input"


class _ThreadHashJobs:
    """Los trabajos de hash de las fuentes externas (``HashJobs`` de la 008) hechos al
    lanzarlos, en el hilo, con el ``WorkerContext`` de la 004 y la función del trabajo
    ``core_content_hash`` (``jobs.content_hash.run``): la misma que en proceso aparte, que
    copia a ``in/`` un GeoPackage con su ``-wal``. Anota el nombre de cada entrada y los
    ficheros que leyó (``bytes``, por papel)."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.done: dict[str, Any] = {}

    def submit(self, request: Any) -> Any:
        job = content_hash.new_job(request)
        folder = job_paths.job_dir(self.base, job.job_uid).create()
        ctx = worker_api.WorkerContext(job, folder, worker_api.QueueSink(),
                                       paths=content_hash.job_paths(request))
        summary = content_hash.run(ctx)
        self.done[request.name] = summary["bytes"]
        return checks.HashResult(digest=encoder.ContentDigest(
            summary["data_sha256"], summary["content_sha256"], summary["normalizer"],
            summary["reader"]))

    def poll(self, ticket: Any) -> Any:
        return ticket

    def cancel(self, ticket: Any) -> None:  # pragma: no cover - nada queda a medias
        raise AssertionError("ningún trabajo de hash se cancela en estas pruebas")


class UntouchedCase(ImportCase):
    """El proyecto de ``ImportCase`` con las fuentes en ``entregas/`` (una carpeta por fuente;
    el GeoPackage de ``wal/`` con 3 líneas que solo están en su ``-wal``) y los trabajos de la
    004 en ``trabajos/``."""

    def setUp(self) -> None:
        super().setUp()
        # Los envoltorios de los trabajos registran los lectores de su lista que falten.
        self.enterContext(mock.patch.dict(readers._REGISTRY))
        self.sources = self.tmp / "entregas"
        for rel, path in DELIVERIES.items():
            target = self.sources / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        _killed_writer(self.sources / WAL_GPKG,
                       [core_gpkg.encode_geometry("LINESTRING", line, 25830, True)
                        for line in WAL_LINES])
        self.assertEqual(self.auxiliary(), WAL_SIDES)
        self.jobs = self.tmp / "trabajos"

    # --- Ayudas -----------------------------------------------------------------------------

    def auxiliary(self) -> list[str]:
        """Los auxiliares de SQLite, GDAL o Access que hay en ``entregas/``."""
        return sorted(rel for path in self.sources.rglob("*")
                      if is_auxiliary(rel := path.relative_to(self.sources).as_posix()))

    @contextmanager
    def untouched(self, *others: Path) -> Iterator[None]:
        """La carpeta de cada fuente (y ``others``) no cambia en el bloque (RF-006-10,
        RF-008-14): mismo listado, tamaños, fechas y sha256, y ningún auxiliar nuevo."""
        with ExitStack() as stack:
            for folder in (self.sources, *others):
                age_folders(folder)
                stack.enter_context(assert_source_untouched(folder))
            yield
        self.assertEqual(self.auxiliary(), WAL_SIDES)

    def run_worker(self, worker: str, handle: Any, params: dict[str, Any],
                   files: dict[str, Path]) -> tuple[dict[str, Any], Any, Any]:
        """El trabajo ``worker`` de la operación ``handle`` en el hilo, con la fuente por
        ``--path`` (``files``, por papel): su resumen, su ``JobOutcome`` para ``ingest_job`` y
        su carpeta. La petición no lleva ninguna ruta (ARQ-11)."""
        request = protocol.new_request(worker, label=f"Importar «{params['name']}»",
                                       owner="gis", params=params, operation_uid=handle.uid,
                                       environment="blender", timeout_s=600.0,
                                       grace_s=gis_jobs.CANCEL_GRACE_S)
        folder = job_paths.job_dir(self.jobs, request.job_uid).create()
        protocol.write_request(folder, request)
        ctx = worker_api.WorkerContext(
            protocol.read_request(folder), folder, worker_api.QueueSink(),
            paths={gis_jobs.path_name(role): path for role, path in files.items()})
        summary = import_geoblender(f"workers.{worker}").main(ctx)
        text = (folder.path / job_paths.REQUEST_FILE).read_text("utf-8")
        shown = str(self.sources)
        for form in (shown, shown.replace("\\", "/"), json.dumps(shown)[1:-1]):
            self.assertNotIn(form, text)
        outcome = operations.JobOutcome(
            request.job_uid, "succeeded", "job_thread", label=request.label,
            folder=folder.path, summary=summary, operation_uid=handle.uid,
            outputs=tuple(operations.OutputPrint(ref.path, ref.sha256, ref.role, size=ref.size)
                          for ref in ctx.outputs))
        return summary, outcome, folder

    def job_spec(self, summary: dict[str, Any], name: str, files: dict[str, Path],
                 settings: dict[str, Any]) -> Any:
        """La entrada de la fuente ``files`` (por papel) con lo que trae el resumen de su
        trabajo: el ``ContentDigest`` de la fuente y las huellas de sus ficheros."""
        source = summary["source"]
        anchors = [inputs.locate_source(path, self.project, self.userdata,
                                        role="main" if role == "main" else "sidecar")
                   for role, path in files.items()]
        prints = [input_model.SourcePrint(source["files"][role]["sha256"],
                                          size=source["files"][role]["size"],
                                          mtime_ns=source["files"][role]["mtime_ns"])
                  for role in files]
        return store.source_input(source["reader"], name, files=anchors, file_prints=prints,
                                  digest=gis_jobs.digest_of(source["digest"]), crs=CRS,
                                  vertical=VERTICAL, settings=settings)

    def import_grid_job(self, name: str, reader: Any, files: dict[str, str],
                        settings: dict[str, Any]) -> Any:
        """``gis.import_dtm`` con ``gis_read_raster``: la rejilla que dejó el trabajo en
        ``out/`` pasa a ``gis_src_<nombre>`` con su entrada; de un ráster no se guarda el
        original."""
        found = {role: self.sources / rel for role, rel in files.items()}
        handle = self.begin(provenance.IMPORT_DTM, settings={"nombre": name},
                            executor="job_thread")
        params = {"reader": reader.id, "name": name, "settings": settings, "crs": CRS_JSON,
                  "vertical": VERTICAL_JSON, "size": found["main"].stat().st_size}
        summary, outcome, folder = self.run_worker(gis_jobs.READ_RASTER, handle, params, found)
        spec = self.job_spec(summary, name, found, settings)
        role = gis_jobs.OUT_SOURCE_GRID.role
        with store.ResultWriter(self.project, handle) as out:
            self.assertIsInstance(out.declare_input(spec), inputs.New)
            out.copy_file(provenance.SOURCE_GRID, name, outcome.file(role),
                          content=gis_jobs.digest_of(summary["outputs"][role]["digest"]),
                          sha256=outcome.output(role).sha256)
            operations.ingest_job(self.project, handle, outcome, out.write,
                                  message=f"MDT «{name}» importado")
        copies = [folder.inputs_dir / f"{gis_jobs.path_name('main')}{path.suffix}"
                  for path in found.values()]
        self.assertEqual(list(out.originals(copies))[-1].result.state, "not_applicable")
        return out.input

    def import_points_job(self) -> Any:
        """``gis.import_points`` con ``gis_import_points``: los puntos y las líneas de rotura
        de ``taludes.csv`` con su entrada y su original, guardado desde la copia verificada
        del trabajo (``in/``)."""
        found = {"main": self.sources / "puntos" / "taludes.csv"}
        handle = self.begin(provenance.IMPORT_POINTS, settings={"nombre": "Taludes"},
                            executor="job_thread")
        params = {"reader": gis_content.POINTS_TEXT.id, "name": "Taludes",
                  "settings": POINT_SETTINGS, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                  "size": found["main"].stat().st_size}
        summary, outcome, folder = self.run_worker(gis_jobs.IMPORT_POINTS, handle, params,
                                                   found)
        spec = self.job_spec(summary, "Taludes", found, POINT_SETTINGS)
        with store.ResultWriter(self.project, handle) as out:
            self.assertIsInstance(out.declare_input(spec), inputs.New)
            out.points("Taludes",
                       gis_jobs.read_points(outcome.file(gis_jobs.OUT_POINTS.role)))
            out.breaklines("Taludes",
                           gis_jobs.read_lines(outcome.file(gis_jobs.OUT_LINES.role)))
            operations.ingest_job(self.project, handle, outcome, out.write,
                                  message="20 puntos y 4 líneas de rotura")
        verified = folder.inputs_dir / f"{gis_jobs.path_name('main')}.csv"
        self.assertEqual(list(out.originals([verified]))[-1].result.state, "stored")
        return out.input

    def import_layer(self, name: str, file: str, layer: str, role: str) -> tuple[Any, Any]:
        """``gis.import_vector`` de la capa ``layer`` de ``file``, leída sobre su copia en la
        caché del proyecto (con su ``-wal``, consolidada); de una capa no se guarda el
        original. Devuelve su entrada y lo leído."""
        handle = self.begin(provenance.IMPORT_VECTOR, settings={"nombre": name, "capa": layer})
        copy = vector.copy_source(self.sources / file,
                                  vector.import_dir(self.project.cache_dir(), handle.uid))
        features = vector.read_layer(copy, layer)
        settings = {"layer": layer, "role": role}
        spec = self.source_spec(gis_content.GPKG_LAYER, name, file, settings=settings)
        with store.ResultWriter(self.project, handle) as out:
            self.assertIsInstance(out.declare_input(spec), inputs.New)
            if role == "points":
                out.points(name, points_mod.points_from_features(features)[0])
            else:
                out.breaklines(name, points_mod.breaklines_from_features(features)[0])
            out.commit(message=f"Capa «{layer}» importada")
        self.assertEqual(list(out.originals([copy]))[-1].result.state, "not_applicable")
        return out.input, features

    def import_all(self) -> dict[str, Any]:
        """Las seis importaciones, cada una con la carpeta de su fuente intacta; sus entradas
        por nombre."""
        found: dict[str, Any] = {}
        for name, reader, files, settings in GRIDS:
            with self.subTest(importacion=name), self.untouched():
                found[name] = self.import_grid_job(name, reader, files, settings)
        with self.subTest(importacion="Taludes"), self.untouched():
            found["Taludes"] = self.import_points_job()
        for name, file, layer, role in LAYERS:
            with self.subTest(importacion=name), self.untouched():
                found[name], _features = self.import_layer(name, file, layer, role)
        return found


class ImportFlowsTest(UntouchedCase):
    def test_imports_leave_the_source_folders_untouched(self) -> None:
        """RF-006-10, RF-008-14, RF-006-26: importar el GeoTIFF, el ASC con su ``.prj``, el
        XYZ y el CSV (en su trabajo, que copia la fuente a ``in/``, y su incorporación al
        proyecto, con el original del CSV) y dos capas de GeoPackage, una con un WAL
        pendiente (sobre su copia en la caché, con las 3 líneas que solo estaban en el
        ``-wal``), deja cada entrada vigente con su lector y la huella de sus ficheros, y la
        carpeta de cada fuente con el mismo listado y el mismo sha256, tamaño y fecha de cada
        fichero, sin ``.aux.xml``, ``-wal``, ``-shm`` ni ``-journal`` nuevos; nada guarda una
        ruta absoluta."""
        before = source_state(self.sources)
        found = self.import_all()
        self.assertEqual(tuple(found), NAMES)
        readers_of = {"MDT Norte": "gis.geotiff@1", "MDT ASC": "gis.asc@1",
                      "MDT XYZ": "gis.xyz_grid@1", "Taludes": "gis.points_text@1",
                      "Puntos GPKG": "gis.gpkg_layer@1", "Roturas WAL": "gis.gpkg_layer@1"}
        for name, entry in found.items():
            with self.subTest(entrada=name):
                self.assertEqual((entry.name, entry.reader, entry.status),
                                 (name, readers_of[name], "current"))
                self.assertEqual([(item.sha256, item.size, item.mtime_ns) for item in entry.files],
                                 [(before.digests[rel], *before.entries[rel])
                                  for rel in self.relative(entry)])
        self.assertEqual(self.relative(found["MDT ASC"]), ["asc/corner.asc", "asc/corner.prj"])
        # La capa del GeoPackage en WAL trae las 3 líneas que solo estaban en su -wal.
        (table,) = self.query("SELECT locator FROM gb_dataset WHERE input_uid = ?",
                              found["Roturas WAL"].uid)
        rows = self.query(f'SELECT geom FROM "{table[0]}" ORDER BY fid')
        self.assertEqual(len(rows), 7)
        for row, line in zip(rows[4:], WAL_LINES, strict=True):
            self.assertTrue(np.array_equal(
                import_geoblender("core.gpkg.wkb").decode_geometry(row[0]).coords, line))
        self.assertEqual(source_state(self.sources).digests, before.digests)
        self.assert_no_absolute_paths()

    def relative(self, entry: Any) -> list[str]:
        """Los ficheros de la entrada, relativos a ``entregas/`` (donde los encuentra)."""
        return [inputs.resolve_source(item, self.project, self.userdata)
                .relative_to(self.sources).as_posix() for item in entry.files]


class InputCheckTest(UntouchedCase):
    def test_checking_the_inputs_leaves_the_source_folders_untouched(self) -> None:
        """RF-008-14, RF-008-09, RF-006-10: tras las seis importaciones, la comprobación de
        apertura (el prefiltro por tamaño y fecha: sin cambios, salvo el GeoPackage en WAL, que
        con su ``-wal`` se hashea, sobre una copia privada) y «Comprobar cambios en las
        entradas» (el hash de cada fuente, en el hilo y en el trabajo de hash, que copia el
        GeoPackage con su ``-wal`` a ``in/``) dan cada entrada con el contenido registrado, sin
        avisos, y no cambian ni crean nada en la carpeta de ninguna fuente."""
        found = self.import_all()
        with self.untouched():
            (*_, last) = checks.open_check_steps(self.project, write=True)
        outcome = last.result
        Verdict = input_check.Verdict
        expected = {name: Verdict.UNCHANGED for name in NAMES} | {"Roturas WAL": Verdict.SAME}
        self.assertEqual({item.name: item.verdict for item in outcome.inputs}, expected)
        self.assertEqual((outcome.input_probes, outcome.texts(), outcome.recorded),
                         ((), (), True))
        with self.untouched():
            (*_, last) = checks.full_check_steps(self.project)
        same = {name: Verdict.SAME for name in NAMES}
        self.assertEqual({item.name: item.verdict for item in last.result.inputs}, same)
        self.assertEqual(last.result.texts(), ())
        # Con todas las fuentes en el trabajo de hash (como las grandes).
        jobs = _ThreadHashJobs(self.jobs / "hash")
        with self.untouched(), mock.patch.object(readers, "INLINE_LIMIT_S", -1.0):
            (*_, last) = checks.full_check_steps(self.project, jobs=jobs)
        self.assertEqual({item.name: item.verdict for item in last.result.inputs}, same)
        self.assertEqual(sorted(jobs.done), sorted(NAMES))
        self.assertEqual(sorted(jobs.done["MDT ASC"]), ["main", "prj"])
        self.assertIn("main-wal", jobs.done["Roturas WAL"])
        with self.project.read() as conn:
            self.assertEqual({entry.name: entry.status for entry in inputs.list_inputs(conn)},
                             {name: "current" for name in found})


class ExportTargetTest(UntouchedCase):
    def test_exports_over_an_input_or_its_folder_are_refused(self) -> None:
        """RF-006-10, RF-008-15 (plan §5.6.6): exportar el MDT como GeoTIFF entregable sobre
        la fuente de una entrada, junto a ella (también su ``.prj`` o el ``-wal`` de un
        GeoPackage) o en una subcarpeta lo rechaza ``check_write_target`` nombrando su
        carpeta y la entrada; sobre la fuente de una entrada que está dentro del proyecto,
        nombrando el fichero; dentro de una carpeta de solo lectura, nombrándola. No se
        escribe nada y ninguna carpeta cambia. En ``exports/`` del proyecto, junto a la fuente
        de dentro del proyecto o en otra carpeta, se exporta."""
        self.import_all()
        inner = self.root / "documentos" / "mdt_interno.tif"
        inner.parent.mkdir()
        shutil.copyfile(DATA / "geotiff" / "f64_strip.tif", inner)  # otros datos: otra entrada
        _handle, out, _records = self.import_grid(str(inner), "MDT interno")
        self.assertEqual(out.input.files[0].anchor, input_model.FileAnchor.PROJECT)
        dossiers = self.tmp / "expedientes"
        (dossiers / "cliente").mkdir(parents=True)
        (dossiers / "cliente" / "acta.pdf").write_bytes(b"%PDF-1.4 acta\n")
        read_only = paths_mod.ReadOnlyDirs.from_sources(str(dossiers), [])
        raster = store.load_raster(self.project, "gis_src_mdt_norte")

        def export(target: Path) -> None:
            inputs.check_write_target(target, project=self.project, read_only=read_only)
            target.parent.mkdir(parents=True, exist_ok=True)
            geotiff.GeoTiffIO().write(raster, target, profile="deliverable")

        mdt = {"folder": "mdt", "name": "MDT Norte"}
        refused = (
            (self.sources / "mdt" / "f32_strip.tif", FOLDER_CODE, mdt),
            (self.sources / "mdt" / "mdt_entrega.tif", FOLDER_CODE, mdt),
            (self.sources / "mdt" / "2026" / "mdt_entrega.tif", FOLDER_CODE, mdt),
            (self.sources / "asc" / "corner.prj", FOLDER_CODE,
             {"folder": "asc", "name": "MDT ASC"}),
            (self.sources / "xyz" / "grid.tif", FOLDER_CODE,
             {"folder": "xyz", "name": "MDT XYZ"}),
            (self.sources / "wal" / "capas.gpkg-wal", FOLDER_CODE,
             {"folder": "wal", "name": "Roturas WAL"}),
            (inner, SOURCE_CODE, {"file": "mdt_interno.tif", "name": "MDT interno"}),
            (dossiers / "cliente" / "mdt.tif", READ_ONLY_CODE, {"folder": str(dossiers)}),
        )
        texts = {
            FOLDER_CODE: "No se puede escribir en la carpeta «mdt»: contiene la fuente de la "
                         "entrada «MDT Norte».",
            SOURCE_CODE: "No se puede escribir en «mdt_interno.tif»: es la fuente de la entrada "
                         "«MDT interno».",
            READ_ONLY_CODE: f"La carpeta «{dossiers}» es de solo lectura en las preferencias de "
                            "Geoblender.",
        }
        for target, code, values in refused:
            existed = target.exists()
            with self.subTest(destino=target.name, codigo=code):
                with (self.untouched(inner.parent, dossiers),
                      self.assertRaises(prov_messages.ProvenanceError) as caught):
                    export(target)
                error = caught.exception
                self.assertEqual((error.code, error.values), (code, values))
                if values.get("folder") in ("mdt", str(dossiers)) or code == SOURCE_CODE:
                    self.assertEqual(str(error), texts[code])
                self.assertEqual(target.exists(), existed)
        self.assertFalse((self.sources / "mdt" / "2026").exists())
        for target in (self.root / "exports" / "mdt_norte.tif",
                       inner.parent / "mdt_entrega.tif", self.tmp / "salidas" / "mdt.tif"):
            with self.subTest(destino=str(target.relative_to(self.tmp))), \
                    self.untouched(dossiers):
                export(target)
            written = reader_mod.read_geotiff(target)
            self.assertTrue(written.grid.same_geometry(raster.grid))
            self.assertEqual(written.source_dtype, "float32")


class ExportMessageTest(unittest.TestCase):
    def test_export_over_an_input_is_refused_by_the_008(self) -> None:
        """RF-006-10, RF-008-15 (plan §5.6.6 y §5.6.9): ``gis.export_over_input`` sale del
        catálogo de ``gis`` y ningún módulo de la extensión lo usa; lo dicen los rechazos de
        ``check_write_target`` de la 008."""
        self.assertNotIn(OLD_CODE, messages.MESSAGES)
        self.assertNotIn(OLD_CODE, [message.code for message in messages.CATALOG])
        used = [path.relative_to(EXTENSION_DIR).as_posix()
                for path in sorted(EXTENSION_DIR.rglob("*.py"))
                if OLD_CODE in path.read_text(encoding="utf-8")]
        self.assertEqual(used, [])
        for code in (FOLDER_CODE, SOURCE_CODE, READ_ONLY_CODE):
            self.assertIn(code, prov_messages.MESSAGES)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Importar un MDT en Blender (spec 006, T28; HU-006-1; plan 006 §5.3.5, §5.5 y §5.6.1 a
§5.6.8).

Proyectos sintéticos de esquema 2 (EPSG:25830 + EPSG:5782, ventana de 699 980 a 700 080 y de
4 399 980 a 4 400 060, paso de 2 m) abiertos en la sesión, con las fuentes en ``entregas/``,
fuera de ellos. Las órdenes ``geoblender.gis_import_dtm`` y ``geoblender.gis_resample_to_grid``
son operadores de la procedencia de la 008 (``ProvenanceAwareOperator``): la puerta, la
operación «en curso», su trabajo de la 004 (``gis_read_raster``, ``gis_resample``) y su
incorporación al proyecto al terminar. En ``blender -b`` los temporizadores no corren: las
pruebas avanzan a mano el monitor de los trabajos. El servicio de CRS de las órdenes (el de
Blender) es uno de prueba con las transformaciones de la 006 (ED50 → ETRS89 con la rejilla
del IGN, 0,2 m; altura elipsoidal → Alicante con el geoide, 0,05 m). :class:`DtmOperatorsCase`
(el proyecto, las fuentes, lanzar una orden y terminar su trabajo) la usa también
``test_ops_dtm_grid`` (la rejilla del proyecto).

- RF-006-27: las dos órdenes sustituyen a las provisionales de la 003 y están disponibles, y
  habilitar registra sus declaraciones de procedencia (el recálculo del remuestreo y la
  reimportación de GeoTIFF, ASC y XYZ); sin proyecto, ``poll`` es falso con el paso previo
  («Primero abra un proyecto (Proyecto ▸ … ▸ Abrir proyecto…)», su ruta en la barra), y en solo
  lectura (el proyecto dentro de una carpeta de solo lectura), con el motivo.
- RF-006-08, RF-006-26 (RF-008-07): importar un GeoTIFF guarda su rejilla de origen
  (``gis_src_<nombre>``, cada celda con el valor de la fuente y el sin dato como sin dato) y su
  entrada, con el nombre lógico, la entrega, los EPSG horizontal y vertical declarados y su
  hash de contenido, sin tocar la carpeta de la fuente.
- RF-006-04, RF-006-09: con el datum «sin declarar», con una extensión que no es de un MDT o
  con un GeoTIFF en JPEG, nada empieza ni se escribe, y el mensaje dice por qué.
- RF-006-05: un MDT en ED50 se importa con la transformación al CRS del proyecto (y su
  precisión) en el informe; sin una de precisión conocida, se rechaza nombrando los dos CRS.
- RF-006-06: un MDT con las cotas unos 50 m por encima del del proyecto no se incorpora hasta
  que la persona lo confirma (la mediana, en el aviso); declarado como altura elipsoidal, se
  transforma y no avisa. Con los mismos datos y otro datum, la importación es una sustitución
  que pide el motivo (RF-008-54, RF-008-11).
- RF-006-04 (T52): el ``.prj`` de un ASC que reconoce el servicio de CRS de la orden no deja en
  el informe la nota de que no se reconoció (tampoco al reimportarlo), y la de uno que no
  reconoce nombra los ficheros del usuario, no sus copias en la carpeta del trabajo.
- RF-006-08, RF-006-11, RF-002-26, RF-006-19 (T51; spec §8): un MDT que sale de la ventana de
  trabajo se importa entero con un aviso en el informe, y la rejilla del proyecto solo cubre la
  ventana; uno a 9 km del GeoOrigin, además, con el aviso de ``core.georef.precision_report``
  (cuántos puntos y el error máximo estimado en mm), que se repite al cargarlo en la vista; uno
  dentro, sin aviso.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import importlib
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "gis"
SITE = ROOT / ".deps" / "site"
WINDOW = (699_980.0, 4_399_980.0, 700_080.0, 4_400_060.0)  # 50 × 40 celdas de 2 m
ED50_WINDOW = (699_880.0, 4_399_780.0, 699_960.0, 4_399_860.0)  # donde cae el MDT en ED50
# La ventana de la verificación de la 006 (F-2): GeoOrigin (700 000; 4 400 000; 0).
EDGE_WINDOW = (699_990.0, 4_399_990.0, 700_040.0, 4_400_030.0)
STEP = 2.0
IMPORT = "geoblender.gis_import_dtm"
RESAMPLE = "geoblender.gis_resample_to_grid"
FRACTION = "gis.resample.min_valid_fraction"
JOB_WAIT_S = 60.0  # plazo de seguridad (la reproyección arranca un proceso aparte)
MAX_TICKS = 300


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _folder_state(folder: Path) -> dict[str, tuple[int, int, str]]:
    return {path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns,
                                                  _sha(path))
            for path in sorted(folder.rglob("*")) if path.is_file()}


class _Shift:
    """Una transformación de prueba: traslada las coordenadas."""

    def __init__(self, info: Any, offset: tuple[float, float, float]) -> None:
        self.info = info
        self.offset = np.array(offset, dtype=np.float64)

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        return np.asarray(xyz, dtype=np.float64) + self.offset


class _FakeCrs:
    """El servicio de CRS de prueba de las órdenes: ED50 → ETRS89 (con o sin precisión
    conocida) y altura elipsoidal → Alicante (unos 50 m de geoide)."""

    def __init__(self, ports: ModuleType, *, known: bool = True) -> None:
        self.ed50 = ports.TransformInfo(
            "Inverse of UTM zone 30N + ED50 to ETRS89 (12) + UTM zone 30N",
            0.2 if known else None, ("es_ign_SPED2ETV2.tif",))
        self.geoid = ports.TransformInfo("ETRS89 to Alicante height (egm08-rednap)", 0.05,
                                         ("es_ign_egm08-rednap.tif",))
        self.asked: list[tuple[Any, ...]] = []
        self.recognised: Any = None  # el CRS que reconoce en el WKT de un .prj
        self.wkts: list[str] = []

    def identify_wkt(self, wkt: str) -> Any:
        self.wkts.append(wkt)
        return self.recognised

    def transformer(self, src: Any, src_v: Any, dst: Any, dst_v: Any) -> _Shift:
        self.asked.append((src.epsg, src_v.kind, dst.epsg, dst_v.epsg))
        if src.epsg == 23030:
            return _Shift(self.ed50, (-110.0, -207.0, 0.0))
        if src_v.kind == "ellipsoidal":
            return _Shift(self.geoid, (0.0, 0.0, -50.0))
        raise AssertionError(f"transformación inesperada: {self.asked[-1]}")


class DtmOperatorsCase(unittest.TestCase):
    """La extensión habilitada una vez para todas; cada prueba, con su proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.jobs_ops = _module("bl.ops.jobs")
        cls.gis_ops = _module("bl.ops.gis")
        cls.core = _module("core.project")
        cls.ports = _module("gis.ports")
        cls.reader = _module("gis.geotiff.reader")
        cls.geotiff = _module("gis.geotiff")
        cls.raster = _module("gis.raster")
        cls.resample = _module("gis.resample")
        cls.grid = _module("gis.grid")
        cls.georef = _module("core.georef")
        catalog = cls.georef.load_catalog()
        cls.crs, cls.vertical = catalog.horizontal(25830), catalog.vertical(5782)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ps.close()
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t28-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.jobs_ops.MONITOR.stop)
        self.addCleanup(self.ps.close)
        self.ps.take_notices()
        self.fake = _FakeCrs(self.ports)
        self.enterContext(mock.patch.object(self.gis_ops, "crs_resolver", lambda: self.fake))
        self.enterContext(mock.patch.object(self.gis_ops, "wheels_site", lambda: SITE))
        self.addCleanup(self.cancel_waiting)
        self.sources = self.tmp / "entregas"

    def cancel_waiting(self) -> None:
        """Cancela lo que una prueba que falló dejó esperando una decisión."""
        for uid in self.gis_ops.waiting_imports():
            bpy.ops.geoblender.gis_import_dtm("EXEC_DEFAULT", pending=uid, decision="CANCEL")

    # --- Ayudas -----------------------------------------------------------------------------

    def open(self, folder: str = "proyectos", window: tuple[float, ...] = WINDOW) -> Any:
        """Un proyecto nuevo con la ventana ``window`` abierto en la sesión, con su
        comprobación de apertura hecha."""
        parent = self.tmp / folder
        parent.mkdir(parents=True, exist_ok=True)
        settings = self.core.ProjectSettings(**settings_values(window=window,
                                                               grid_step_m=STEP))
        project = self.core.create_project(parent, settings, self.ps.session(),
                                           self.ps.userdata()).project
        self.ps.attach(project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = project
        return project

    def source(self, relative: str, name: str | None = None) -> Path:
        """Una copia de ``tests/data/gis/<relative>`` en ``entregas/``."""
        target = self.sources / (name or Path(relative).name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATA / relative, target)
        return target

    def written(self, raster: Any, name: str) -> Path:
        """Una fuente GeoTIFF escrita con ``raster`` en ``entregas/``."""
        target = self.sources / name
        target.parent.mkdir(parents=True, exist_ok=True)
        self.geotiff.GeoTiffIO().write(raster, target, profile="project")
        return target

    def source_raster(self, path: Path, crs: Any = None) -> Any:
        found = self.reader.read_geotiff(path)
        return self.raster.Raster(found.grid, found.values, crs or found.declared_crs,
                                  self.vertical)

    def run_op(self, idname: str, **props: Any) -> tuple[set[str], str | None]:
        """Ejecuta la orden ``idname`` (``EXEC_DEFAULT``) y devuelve su final y la operación
        que dejó pendiente de incorporar (su trabajo ya lanzado), o ``None``."""
        before = set(self.session.pending_ingests())
        group, name = idname.split(".")
        result = getattr(getattr(bpy.ops, group), name)("EXEC_DEFAULT", **props)
        launched = {job: op for job, op in self.session.pending_ingests().items()
                    if job not in before}
        self.assertLessEqual(len(launched), 1)
        return result, next(iter(launched.values()), None)

    def finish(self) -> None:
        """Avanza a mano el monitor de los trabajos y el temporizador de las incorporaciones
        por pasos (T50) hasta que no queda ningún trabajo activo ni nada por incorporar."""
        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        while time.monotonic() < deadline:
            self.jobs_ops.tick()
            self.gis_ops.incorporation_tick()
            if not any(snapshot.active for snapshot in runner.snapshots()):
                self.jobs_ops.tick()
                while self.gis_ops.pending_incorporations():
                    self.gis_ops.incorporation_tick()
                return
            time.sleep(0.002)
        self.fail("los trabajos no terminan")

    def launch(self, idname: str, **props: Any) -> str:
        """La orden y su trabajo hasta el final; devuelve el uid de su operación."""
        result, op_uid = self.run_op(idname, **props)
        self.assertEqual(result, {"FINISHED"})
        self.assertIsNotNone(op_uid)
        self.finish()
        return op_uid

    def import_dtm(self, path: Path, name: str, **props: Any) -> str:
        props.setdefault("vertical", "PROJECT")
        return self.launch(IMPORT, filepath=str(path), name=name, **props)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operation(self, uid: str) -> tuple[Any, ...]:
        (row,) = self.rows("SELECT op_type, status, status_reason, message, settings, software, "
                           "executor, supersedes_uid FROM gb_operation WHERE uid = ?", uid)
        return row

    def dataset(self, name: str) -> tuple[Any, ...]:
        (row,) = self.rows("SELECT uid, locator, input_uid, content_sha256, operation_uid FROM "
                           "gb_dataset WHERE name = ? AND status = 'current'", name)
        return row

    def stored(self, name: str) -> Any:
        return _module("gis.store").load_raster(self.project, name)

    def counts(self) -> tuple[int, int, int]:
        (row,) = self.rows("SELECT (SELECT count(*) FROM gb_operation), "
                           "(SELECT count(*) FROM gb_dataset), (SELECT count(*) FROM gb_input)")
        return row

    def assertSameCells(self, got: Any, expected: Any) -> None:
        self.assertTrue(got.grid.same_geometry(expected.grid))
        self.assertTrue(np.array_equal(got.values, expected.values, equal_nan=True))


class DtmImportTest(DtmOperatorsCase):
    def test_real_operators_and_their_declarations(self) -> None:
        """RF-006-27, RF-008-26, RF-008-11 (plan §5.6.3 y §5.6.8): las dos órdenes son las
        reales (no las provisionales de la 003) y están disponibles; habilitar registra el
        ``OperationDef`` de la importación (sin recálculo) y el del remuestreo (con su
        recálculo) y los importadores de GeoTIFF, ASC y XYZ en malla; quitarlo y volverlo a
        poner deja los registros como estaban (idempotente)."""
        commands = _module("bl.ui.commands")
        contract = _module("core.provenance.contract")
        for idname in (IMPORT, RESAMPLE):
            with self.subTest(orden=idname):
                cls = commands.registered_class(idname)
                self.assertIsNotNone(cls)
                self.assertFalse(commands.is_provisional(cls))
                self.assertTrue(commands.is_available(idname))
        # Con las de la T29 (los TIN, las conversiones y las importaciones de puntos y capas),
        # la de la T30 (las curvas de nivel) y las de la T31 (las exportaciones).
        expected = (["gis.contours", "gis.export_gpkg", "gis.export_raster", "gis.grid_to_tin",
                     "gis.import_dtm", "gis.import_points", "gis.import_vector", "gis.resample",
                     "gis.tin_from_contours", "gis.tin_from_points", "gis.tin_to_grid"],
                    ["gis.asc", "gis.geotiff", "gis.gpkg_layer", "gis.points_text",
                     "gis.xyz_grid"])

        def ours() -> tuple[list[str], list[str]]:
            return (sorted(key for key in contract.OPERATIONS if key.startswith("gis.")),
                    sorted(key for key in contract.IMPORTERS if key.startswith("gis.")))

        self.assertEqual(ours(), expected)
        self.assertIsNone(contract.OPERATIONS["gis.import_dtm"].recompute)
        self.assertTrue(callable(contract.OPERATIONS["gis.resample"].recompute))
        self.addCleanup(self.gis_ops.register)
        for _ in range(2):
            self.gis_ops.unregister()
            self.assertEqual(ours(), ([], []))
        for _ in range(2):
            self.gis_ops.register()
            self.assertEqual(ours(), expected)

    def test_poll_needs_a_writable_project(self) -> None:
        """RF-006-27 (plan §5.5; RF-008-15): sin proyecto, las dos órdenes no están
        disponibles y dicen el paso previo; con el proyecto dentro de una carpeta de solo
        lectura, tampoco, con el motivo; abierto en escritura, sí."""
        self.ps.close()
        search = _module("core.catalog.search")
        path = search.path_text(_module("bl.ui.commands").catalog(), "geoblender.core_open_project",
                                "es")
        self.assertTrue(path.startswith("Proyecto ▸") and path.endswith("Abrir proyecto…"), path)
        first = f"Primero abra un proyecto ({path})"
        for idname in (IMPORT, RESAMPLE):
            with self.subTest(orden=idname):
                group, name = idname.split(".")
                self.assertFalse(getattr(getattr(bpy.ops, group), name).poll())
                self.assertEqual(self.gis_ops.unavailable_reason(), first)
        project = self.open("expedientes")
        root = Path(project.root)
        self.assertIsNone(self.gis_ops.unavailable_reason())
        self.assertTrue(bpy.ops.geoblender.gis_import_dtm.poll())
        self.ps.close()
        paths = _module("core.paths")
        read_only = paths.ReadOnlyDirs.from_sources(str(self.tmp / "expedientes"), [])
        opened = self.core.open_project(root, self.ps.session(), self.ps.userdata(),
                                        read_only=read_only).project
        self.ps.attach(opened)
        self.assertFalse(opened.writable)
        self.assertFalse(bpy.ops.geoblender.gis_import_dtm.poll())
        self.assertFalse(bpy.ops.geoblender.gis_resample_to_grid.poll())
        reason = self.gis_ops.unavailable_reason()
        self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
        self.assertIn("solo lectura", reason[len("Proyecto en solo lectura: "):])

    def test_import_keeps_the_source_cells_and_registers_its_input(self) -> None:
        """RF-006-08, RF-006-26, RF-008-07, RF-008-54: importar un GeoTIFF (con el datum del
        proyecto declarado) deja ``gis_src_mdt_dron`` con las celdas de la fuente bit a bit (su
        sin dato, sin dato) y su entrada con el nombre lógico, la entrega, los EPSG declarados y
        su hash de contenido; la operación queda hecha con el informe, que también llega a
        los avisos, y la carpeta de la fuente no cambia. Importarla otra vez igual reutiliza
        la entrada: la operación queda cancelada con el aviso y no se escribe nada."""
        self.open()
        path = self.source("geotiff/f64_strip.tif", "mdt/dron_2026.tif")
        before = _folder_state(self.sources)
        op_uid = self.import_dtm(path, "MDT dron", received_at="24/09/2026",
                                 received_from="Vuelo de dron")
        self.assertEqual(_folder_state(self.sources), before)
        op_type, status, _reason, message, settings, software, executor, _ = \
            self.operation(op_uid)
        self.assertEqual((op_type, status, software, executor),
                         ("gis.import_dtm", "done", "{}", "job_thread"))
        uid, locator, input_uid, content, writer = self.dataset("gis_src_mdt_dron")
        self.assertEqual(writer, op_uid)
        self.assertRegex(locator, r"^rasters/gis_src_mdt_dron_[0-9a-f]{8}\.tif$")
        self.assertSameCells(self.stored("gis_src_mdt_dron"), self.source_raster(path))
        (entry,) = self.rows("SELECT name, reader, crs_h, crs_v, content_sha256, received_at, "
                             "received_from, status, original FROM gb_input WHERE uid = ?",
                             input_uid)
        self.assertEqual(entry[:4], ("MDT dron", "gis.geotiff@1", '{"epsg":25830}',
                                     '{"epsg":5782}'))
        self.assertEqual(entry[5:], ("2026-09-24", "Vuelo de dron", "current",
                                     "not_applicable"))
        self.assertRegex(entry[4], r"^[0-9a-f]{64}$")
        self.assertIn("MDT ráster «MDT dron» importado como gis_src_mdt_dron", message)
        self.assertIn("64 × 48 celdas", message)
        self.assertEqual(json.loads(settings)["control"]["gis.import.max_cells"], 100_000_000)
        self.assertIn(message, self.ps.take_notices())
        # La misma fuente con los mismos ajustes se reutiliza: cancelada con el aviso.
        before = self.counts()
        again = self.import_dtm(path, "MDT dron")
        _type, status, reason, *_ = self.operation(again)
        self.assertEqual(status, "cancelled")
        self.assertIn("MDT dron", reason)
        self.assertEqual(self.counts()[1:], before[1:])  # ni datos ni entradas nuevos
        self.assertNotIn(again, self.session.pending_ingests().values())

    def test_undeclared_datum_or_unsupported_format_write_nothing(self) -> None:
        """RF-006-04, RF-006-09: con el datum vertical «sin declarar» (el GeoTIFF no lo
        declara), con una extensión que no es de un MDT o con un GeoTIFF en JPEG, la orden se
        niega con el motivo y no empieza ninguna operación ni escribe nada."""
        project = self.open()
        root = Path(project.root)
        before_files = _folder_state(root / "rasters")
        before = self.counts()
        pending = self.session.pending_ingests()
        cases = (
            (self.source("geotiff/f64_strip.tif"), "UNDECLARED", "no declara su datum vertical"),
            (self.source("geotiff/f64_strip.tif", "orto.png"), "PROJECT",
             "la extensión «.png» no es de un formato admitido"),
            (self.source("geotiff/u8_jpeg.tif"), "PROJECT", "JPEG"),
        )
        for path, vertical, expected in cases:
            with self.subTest(fuente=path.name), self.assertRaises(RuntimeError) as caught:
                self.run_op(IMPORT, filepath=str(path), name="MDT", vertical=vertical)
            self.assertIn(expected, str(caught.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(_folder_state(root / "rasters"), before_files)
        self.assertEqual(self.session.pending_ingests(), pending)

    def test_ed50_import_reports_its_transformation(self) -> None:
        """RF-006-05: un MDT en ED50 (EPSG:23030, declarado por el fichero) se importa en su
        CRS con la transformación al del proyecto y su precisión en el informe; sin una
        transformación de precisión conocida, se rechaza nombrando los dos CRS y no empieza
        nada. RF-006-08 (T51): el aviso de la ventana de trabajo, con su extensión
        transformada al CRS del proyecto."""
        self.open()
        path = self.source("geotiff/f32_epsg23030.tif")
        self.fake = _FakeCrs(self.ports, known=False)
        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            self.run_op(IMPORT, filepath=str(path), name="Plano antiguo", vertical="PROJECT")
        self.assertIn("No hay una transformación de precisión conocida de EPSG:23030",
                      str(caught.exception))
        self.assertIn("EPSG:25830", str(caught.exception))
        self.assertEqual(self.counts(), before)
        self.fake = _FakeCrs(self.ports)
        op_uid = self.import_dtm(path, "Plano antiguo")
        message = self.operation(op_uid)[3]
        self.assertIn("ED50 to ETRS89 (12)", message)
        self.assertIn("precisión 0,2 m", message)
        self.assertIn("es_ign_SPED2ETV2.tif", message)
        (crs_h,) = self.rows("SELECT crs_h FROM gb_input WHERE name = 'Plano antiguo'")[0]
        self.assertEqual(crs_h, '{"epsg":23030}')
        # T51 (spec §8): transformado al CRS del proyecto, cae fuera de la ventana; sin el
        # aviso de 8 km (en otro CRS, la vista no lo muestra sin transformarlo).
        fmt = _module("core.i18n").format_number
        self.assertIn(f"El MDT «Plano antiguo» sale de la ventana de trabajo (X "
                      f"{fmt(699_980, 2)} a {fmt(700_080, 2)}, Y {fmt(4_399_980, 2)} a "
                      f"{fmt(4_400_060, 2)}): sus celdas con dato, transformadas al CRS del "
                      f"proyecto, van de X {fmt(699_890, 2)} a {fmt(699_954, 2)} y de Y "
                      f"{fmt(4_399_793, 2)} a {fmt(4_399_841, 2)}.", message)
        self.assertNotIn("GeoOrigin", message)

    def test_asc_prj_note_names_the_user_files(self) -> None:
        """RF-006-04, RF-006-08, RF-008-11 (T52; constitución, principio 10): un ASC cuyo
        ``.prj`` reconoce el servicio de CRS de la orden se importa con ese CRS y su informe no
        dice que no se reconoció, tampoco al reimportarlo; con un ``.prj`` que no reconoce (el
        CRS, tecleado), la nota nombra los ficheros del usuario («dxdy.prj», «dxdy.asc»),
        nunca sus copias en la carpeta del trabajo («source_main…»)."""
        self.open()
        path = self.source("asc/corner.asc", "mdt/mdt05.asc")
        self.source("asc/corner.prj", "mdt/mdt05.prj")
        self.fake.recognised = self.crs
        op_uid = self.import_dtm(path, "MDT05")
        _type, status, _reason, message, *_ = self.operation(op_uid)
        self.assertEqual(status, "done")
        self.assertEqual(len(self.fake.wkts), 1)
        self.assertIn("MDT ráster «MDT05» importado", message)
        self.assertNotIn("no se ha reconocido", message)
        self.assertNotIn("source_main", message)
        (input_uid, crs_h), = self.rows("SELECT uid, crs_h FROM gb_input WHERE name = 'MDT05'")
        self.assertEqual(crs_h, '{"epsg":25830}')
        contract = _module("core.provenance.contract")
        handle = self.gis_ops.reimport_dtm(contract.ReimportRequest(
            self.project, input_uid, "Nueva entrega", settings={"nodata_override": 788.589}))
        self.finish()
        _type, status, _reason, message, *_ = self.operation(handle.uid)
        self.assertEqual(status, "done")
        self.assertNotIn("no se ha reconocido", message)
        self.assertNotIn("source_main", message)

        self.fake.recognised = None
        other = self.source("asc/dxdy.asc", "malla/dxdy.asc")
        self.source("asc/corner.prj", "malla/dxdy.prj")
        op_uid = self.import_dtm(other, "Malla", crs="EPSG:25830")
        _type, status, _reason, message, *_ = self.operation(op_uid)
        self.assertEqual(status, "done")
        self.assertIn("El CRS que declara «dxdy.prj» no se ha reconocido en el catálogo de "
                      "Geoblender: declare el CRS de «dxdy.asc» al importarlo.", message)
        self.assertNotIn("source_main", message)

    def written_dtm(self, west: float, north: float, size: int, name: str) -> tuple[Any, Path]:
        """Un MDT de ``size`` × ``size`` celdas de 1 m con su esquina noroeste en
        (``west``; ``north``), escrito en ``entregas/<name>``."""
        grid = self.grid.Grid(west, north, 1.0, 1.0, size, size)
        xx, _yy = grid.centers()
        raster = self.raster.Raster(grid, 800.0 + 0.01 * (xx - 700_000.0), self.crs,
                                    self.vertical)
        return raster, self.written(raster, name)

    def test_dtm_outside_the_window_or_far_from_the_origin(self) -> None:
        """RF-006-08, RF-006-11, RF-002-26, RF-006-19 (T51; spec §8, «MDT que sale de la
        ventana de trabajo o a más de 8 km del GeoOrigin»; reproducción de F-2 de la
        verificación de la 006). Con el GeoOrigin en (700 000; 4 400 000) y la ventana de
        699 990 a 700 040 y de 4 399 990 a 4 400 030:

        - un MDT dentro de la ventana se importa sin aviso;
        - uno de 40 × 40 m que sale de ella por el este y por el norte se importa entero, con
          el aviso que dice su extensión y la de la ventana, y la rejilla del proyecto solo
          cubre la ventana;
        - uno a 9 km al este se importa entero con ese aviso y con el de
          ``core.georef.precision_report`` de los centros de sus celdas con dato («100 puntos
          están a más de 8 000 m del GeoOrigin…», 0,488 mm), y al cargarlo en la vista lo
          vuelve a decir de lo que se carga; el de 40 × 40 m se carga sin aviso."""
        project = self.open(window=EDGE_WINDOW)
        self.assertEqual(project.origin.as_tuple(), (700_000, 4_400_000, 0))
        fmt = _module("core.i18n").format_number
        views = _module("bl.scene.views")

        _inside, path = self.written_dtm(700_000.0, 4_400_020.0, 10, "dentro/dentro.tif")
        _type, status, _reason, message, *_ = self.operation(self.import_dtm(path, "Dentro"))
        self.assertEqual(status, "done")
        self.assertIn("MDT ráster «Dentro» importado", message)
        self.assertNotIn("ventana de trabajo", message)
        self.assertNotIn("GeoOrigin", message)

        def window_note(name: str, extent: tuple[float, ...]) -> str:
            west, south, east, north = (fmt(value, 2) for value in extent)
            return (f"El MDT «{name}» sale de la ventana de trabajo (X {fmt(699_990, 2)} a "
                    f"{fmt(700_040, 2)}, Y {fmt(4_399_990, 2)} a {fmt(4_400_030, 2)}): sus "
                    f"celdas con dato van de X {west} a {east} y de Y {south} a {north}. Se "
                    "importa entero; la rejilla del proyecto solo cubre la ventana")

        half, path = self.written_dtm(700_020.0, 4_400_050.0, 40, "fuera/medio.tif")
        self.ps.take_notices()
        _type, status, _reason, message, *_ = self.operation(
            self.import_dtm(path, "Medio fuera"))
        self.assertEqual(status, "done")
        self.assertIn(window_note("Medio fuera", (700_020, 4_400_010, 700_060, 4_400_050)),
                      message)
        self.assertNotIn("GeoOrigin", message)
        self.assertIn(message, self.ps.take_notices())
        self.assertSameCells(self.stored("gis_src_medio_fuera"), half)  # entero
        self.launch(RESAMPLE, source="gis_src_medio_fuera", name="Medio")
        target = self.grid.project_grid(project.window, project.grid_step_m)
        self.assertTrue(self.stored("gis_dtm_medio").grid.same_geometry(target))

        far, path = self.written_dtm(709_000.0, 4_400_020.0, 10, "fuera/lejos.tif")
        _type, status, _reason, message, *_ = self.operation(self.import_dtm(path, "Lejos"))
        self.assertEqual(status, "done")
        self.assertSameCells(self.stored("gis_src_lejos"), far)
        xx, yy = far.grid.centers()
        precision = self.georef.precision_report(np.column_stack([xx.ravel(), yy.ravel()]),
                                                 project.origin)
        self.assertEqual(precision.points_outside, 100)
        self.assertIn("100 puntos están a más de 8", precision.message)
        self.assertIn("0,488 mm", precision.message)
        self.assertIn(window_note("Lejos", (709_000, 4_400_010, 709_010, 4_400_020)), message)
        self.assertIn(f"MDT «Lejos», centros de las celdas con dato: {precision.message}",
                      message)

        outcome = views.load_datasets(bpy.context, project, ["gis_src_lejos",
                                                             "gis_src_medio_fuera"])
        self.addCleanup(views.unload_datasets, views.loaded_uids(outcome.objects))
        self.assertEqual(outcome.loaded, ("gis_src_lejos", "gis_src_medio_fuera"))
        self.assertEqual(outcome.notes, (f"«gis_src_lejos» en la vista: {precision.message}",))

    def test_ellipsoidal_heights_ask_before_finishing(self) -> None:
        """RF-006-06, RF-008-54, RF-008-11: con un MDT del proyecto, un MDT con las cotas unos
        50 m por encima declarado en el datum del proyecto no se incorpora (ni su entrada ni
        su rejilla) hasta que la persona lo confirma, con la mediana en el aviso; los mismos
        datos declarados como altura elipsoidal son una sustitución que pide el motivo y,
        con él, se importan con la transformación al geoide en el informe y sin aviso.
        RF-004-07 (T57): cancelarla en su diálogo lo informa la orden; la línea de su trabajo
        en la barra de estado dice «Operación cancelada» y el registro de Blender no lo
        repite."""
        self.open()
        base = self.source("geotiff/f64_strip.tif", "mdt/base.tif")
        self.import_dtm(base, "MDT base")
        self.launch(RESAMPLE, source="gis_src_mdt_base", name="Base")
        raster = self.source_raster(base)
        high = self.written(dataclasses.replace(raster, values=raster.values + 50.0),
                            "dron/dron_elipsoidal.tif")
        result, op_uid = self.run_op(IMPORT, filepath=str(high), name="Dron", vertical="PROJECT")
        self.assertEqual(result, {"FINISHED"})
        self.finish()
        self.assertEqual(self.operation(op_uid)[1], "running")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_input WHERE name = 'Dron'"), [(0,)])
        warning = ("La mediana de la diferencia con el MDT «gis_dtm_base» es de 50 m: las "
                   "cotas pueden ser alturas elipsoidales")
        notices = self.ps.take_notices()
        self.assertTrue(any(warning in text for text in notices), notices)
        self.assertIn(op_uid, self.gis_ops.waiting_imports())
        sent = len(self.jobs_ops.sent_reports())
        self.assertEqual(bpy.ops.geoblender.gis_import_dtm("EXEC_DEFAULT", pending=op_uid,
                                                           decision="CANCEL"), {"FINISHED"})
        self.assertEqual(self.operation(op_uid)[1], "cancelled")
        self.assertEqual(self.jobs_ops.MONITOR.view().ending.state, "cancelled")
        self.assertEqual(self.jobs_ops.sent_reports()[sent:], ())
        result, op_uid = self.run_op(IMPORT, filepath=str(high), name="Dron", vertical="PROJECT")
        self.finish()
        self.assertIn(op_uid, self.gis_ops.waiting_imports())
        self.assertEqual(bpy.ops.geoblender.gis_import_dtm("EXEC_DEFAULT", pending=op_uid,
                                                           decision="CONTINUE"), {"FINISHED"})
        self.assertEqual(self.operation(op_uid)[1], "done")
        (first,) = self.rows("SELECT uid FROM gb_input WHERE name = 'Dron'")[0]

        result, op_uid = self.run_op(IMPORT, filepath=str(high), name="Dron",
                                     vertical="ELLIPSOIDAL")
        self.finish()
        notices = " ".join(self.ps.take_notices())
        self.assertIn("los mismos datos", notices)
        with self.assertRaises(RuntimeError):  # sin motivo, sigue esperando
            bpy.ops.geoblender.gis_import_dtm("EXEC_DEFAULT", pending=op_uid,
                                              decision="CONTINUE")
        self.assertEqual(self.operation(op_uid)[1], "running")
        self.assertEqual(bpy.ops.geoblender.gis_import_dtm(
            "EXEC_DEFAULT", pending=op_uid, decision="CONTINUE",
            reason="El dron vuela sin geoide"), {"FINISHED"})
        _type, status, _reason, message, *_ = self.operation(op_uid)
        self.assertEqual(status, "done")
        self.assertIn("egm08-rednap", message)
        self.assertIn("precisión 0,05 m", message)
        self.assertNotIn("alturas elipsoidales", message)
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", first),
                         [("superseded",)])
        self.assertEqual(self.rows("SELECT crs_v, previous_uid FROM gb_input WHERE name = 'Dron' "
                                   "AND status = 'current'"),
                         [('{"ellipsoidal":4937}', first)])
        self.assertEqual(self.gis_ops.waiting_imports(), {})


if __name__ == "__main__":
    unittest.main()

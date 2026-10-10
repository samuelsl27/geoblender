# SPDX-License-Identifier: GPL-3.0-or-later
"""Cargar y descargar datos del proyecto en la vista (spec 006, T27; RF-006-19, RF-006-20,
RF-006-21, RF-006-22, RF-006-29; plan 006 §5.1, §5.5 y §5.6.7; ADR-0005).

Un proyecto sintético de esquema 2 (GeoOrigin (700 000; 4 400 000; 0), EPSG:25830 + EPSG:5782)
con datos de la topografía a unos 8 km del origen, en las cuatro direcciones: una rejilla de
1 m (``gis_dtm_mdt_lejano``, 10 × 10 celdas con un hueco), un TIN (``gis_tin_topo_lejano``,
bloqueado), curvas de nivel (``gis_cnt_curvas_lejanas``, obsoletas: cambió la equidistancia
que leyó su operación), los puntos y las líneas de rotura de un CSV importado
(``gis_pts_taludes_lejanos`` y ``gis_brk_taludes_lejanos``) y una rejilla que falta
(``gis_dtm_mdt_falta``). Se escribe con ``gis.store.ResultWriter`` y la procedencia de la 008,
como lo harán los operadores, y se abre en la sesión.

- RF-006-19: ``geoblender.core_load_into_view`` crea los objetos en coordenadas locales y con
  matriz identidad; vueltos a absolutas (``core.georef.local_to_world``), cada vértice queda a
  ≤ 0,5 mm del dato (a ±8 km), con los triángulos de la rejilla y del TIN y las aristas de las
  líneas.
- RF-006-29 (plan §5.6.7): cada objeto lleva ``Object.geoblender`` (tipo, dato, proyecto, hash
  de contenido, estado, fecha de su operación y obsoleto), con nombre generado, en la colección
  de su dato dentro de «Datos base / Topografía»; el ancla del proyecto, en «Proyecto», tiene
  las esquinas absolutas de la ventana en texto; el recorte de cada Vista 3D cubre lo cargado
  con lejano/cercano ≤ 10⁵. Se cargan los vigentes, los bloqueados y los dañados con su marca,
  y de uno que falta se avisa sin cargarlo. Cargar no registra ninguna operación ni cambia el
  proyecto.
- RF-006-21: una malla con las caras al revés no se muestra (``gis.mesh_invalid``).
- RF-006-22: la rejilla de 1 m se carga también en sus niveles de 2 y 5 m (media por área) y
  se pasa de uno a otro sin cambiar la rejilla de cálculo.
- RF-006-20: descargar quita los objetos y sus mallas y no cambia el proyecto (hash de sus
  ficheros); Ctrl+Z tras cargar deshace solo la vista.
- Principio 8: registrar y desregistrar la extensión deja ``bpy.types`` como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Vector

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.core_fixtures import settings_values

LIMIT_M = 0.0005  # RF-006-19: ≤ 0,5 mm a ±8 km
FAR_M = 7_990.0  # los datos, a unos 8 km del GeoOrigin en X y en Y
CLIP_RATIO_MAX = 1e5
INTERVAL = "gis.contours.interval_m"
PYPROJ = {"pyproj": "3.8.0"}
TRIANGULATOR = {"triangulator": "pure@1"}
POINT_COLUMNS = {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5}
POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                  "columns": POINT_COLUMNS, "line_kind": "hard"}
# Los puntos del CSV, unos 8 km al suroeste: tres del terreno y dos líneas de rotura.
CSV_TEXT = """P;X;Y;Z;Código;Línea
1;692000,123;4392000,377;801,251;TN;
2;692004,456;4392001,019;801,749;TN;
3;692002,987;4392004,263;802,127;TN;
4;692000,011;4392002,003;801,003;C1;C1
5;692004,007;4392002,509;801,501;C1;C1
6;692000,503;4392003,001;801,101;P1;P1
7;692003,751;4392003,503;801,603;P1;P1
8;692004,253;4392004,007;801,907;P1;P1
"""
OBJECT_PROPS = ("kind", "dataset_uid", "project_uid", "content_sha256", "stale", "status",
                "date")
STATUS = {"current": "CURRENT", "blocked": "BLOCKED", "damaged": "DAMAGED"}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _recompute(request: object) -> object:  # pragma: no cover - aquí no se recalcula
    raise AssertionError("no se recalcula en estas pruebas")


def _grid_raster(gis: SimpleNamespace, crs: Any, vertical: Any) -> Any:
    """La rejilla de 1 m del sureste: 10 × 10 celdas de (707 990; 4 392 010) a
    (708 000; 4 392 000), cotas con decimales y un hueco en la esquina SE."""
    rows, cols = np.mgrid[0:10, 0:10]
    values = 800.0 + 0.5 * cols - 0.25 * rows + 0.001 * (rows * 10 + cols) + 0.0004
    values[9, 9] = np.nan
    grid = gis.grid.Grid(707_990.0, 4_392_010.0, 1.0, 1.0, 10, 10)
    return gis.raster.Raster(grid, values, crs, vertical)


def _tin(gis: SimpleNamespace) -> Any:
    """Un TIN de 5 vértices y 4 triángulos al noroeste."""
    xy = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [2.0, 2.0]])
    xy += (692_000.123, 4_408_000.789)
    z = np.array([800.123, 801.017, 802.509, 801.511, 803.253])
    faces = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.int32)
    return gis.tin.Tin(np.column_stack([xy, z]), faces, np.empty((0, 2), np.int32),
                       np.zeros(5, np.uint8), triangulator="pure@1")


def _contours(gis: SimpleNamespace) -> list[Any]:
    """Una curva abierta y otra cerrada (maestra) al noreste."""
    first = np.array([[708_000.517, 4_408_001.033, 801.0], [708_002.071, 4_408_002.509, 801.0],
                      [708_003.553, 4_408_001.257, 801.0]])
    ring = np.array([[708_001.013, 4_408_001.011, 805.0], [708_003.019, 4_408_001.017, 805.0],
                     [708_003.023, 4_408_003.029, 805.0], [708_001.031, 4_408_003.037, 805.0]])
    return [gis.contours.ContourLine(first, 801.0, False, False),
            gis.contours.ContourLine(ring, 805.0, True, True)]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_files(root: Path) -> dict[str, str]:
    """El sha256 de cada fichero del proyecto, por su ruta relativa."""
    return {path.relative_to(root).as_posix(): _sha(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


class ViewProject:
    """El proyecto sintético de la prueba y lo que se escribió en él (absoluto, float64)."""

    def __init__(self, folder: Path) -> None:
        gis = SimpleNamespace(**{name: _module(f"gis.{name}") for name in (
            "grid", "raster", "tin", "contours", "points", "store", "provenance", "content")})
        self.gis = gis
        core = _module("core.project")
        ps = _module("bl.scene.project_session")
        contract = _module("core.provenance.contract")
        operations = _module("core.provenance.operations")
        op_types = (gis.provenance.RESAMPLE, gis.provenance.TIN_FROM_POINTS,
                    gis.provenance.CONTOURS, gis.provenance.IMPORT_POINTS)
        defs = gis.provenance.operation_defs(
            {name: _recompute for name in op_types if name in gis.provenance.REPEATABLE},
            op_types=op_types)
        parent = folder / "proyectos"
        parent.mkdir()
        settings = core.ProjectSettings(**settings_values())
        self.project = core.create_project(parent, settings, ps.session(),
                                           ps.userdata()).project
        self.root = Path(self.project.root)
        self.crs, self.vertical = gis.store.project_references(self.project)
        registered = []  # los que la extensión aún no registra (T28 registra gis.resample)
        for definition in defs:
            if definition.op_type not in contract.OPERATIONS:
                contract.register_operation(definition)
                registered.append(definition.op_type)
        try:
            def begin(op_type: str, **kw: Any) -> Any:
                kw.setdefault("settings", {"nombre": "prueba"})
                return operations.begin_operation(self.project, op_type, executor="blender",
                                                  **kw)

            def write(op_type: str, fill: Any, **kw: Any) -> None:
                software = kw.pop("software", None)
                with gis.store.ResultWriter(self.project, begin(op_type, **kw)) as out:
                    fill(out)
                    out.commit(software=software, message="Datos de la prueba de la vista")

            self.raster = _grid_raster(gis, self.crs, self.vertical)
            write(gis.provenance.RESAMPLE, lambda out: out.raster("MDT Lejano", self.raster),
                  software=PYPROJ, params=["gis.resample.min_valid_fraction"])
            near = _grid_raster(gis, self.crs, self.vertical)
            write(gis.provenance.RESAMPLE, lambda out: out.raster("MDT Falta", near),
                  software=PYPROJ)
            self.tin = _tin(gis)
            write(gis.provenance.TIN_FROM_POINTS, lambda out: out.tin("Topo Lejano", self.tin),
                  software=TRIANGULATOR)
            self.contours = _contours(gis)
            write(gis.provenance.CONTOURS,
                  lambda out: out.contours("Curvas Lejanas", self.contours), params=[INTERVAL])
            self.points, self.lines = self._import_points(folder, begin)
        finally:
            for op_type in reversed(registered):
                contract.unregister_operation(op_type)
        self._marks()

    def _import_points(self, folder: Path, begin: Any) -> tuple[Any, Any]:
        """``gis.import_points`` del CSV (fuera del proyecto), declarado en las referencias
        del proyecto."""
        gis = self.gis
        inputs = _module("core.inputs")
        input_model = _module("core.inputs.model")
        hashing = _module("core.hashing")
        readers = _module("core.content.readers")
        read_table = _module("interop.csv_tables").read_table
        ps = _module("bl.scene.project_session")
        sources = folder / "fuentes"
        sources.mkdir()
        source = sources / "taludes.csv"
        source.write_bytes(CSV_TEXT.encode("utf-8"))
        reader = gis.content.POINTS_TEXT
        anchor = inputs.locate_source(source, self.project, ps.userdata(), role="main")
        prints = [input_model.SourcePrint(hashing.sha256_file(source),
                                          size=source.stat().st_size,
                                          mtime_ns=source.stat().st_mtime_ns)]
        declarations = gis.store.source_declarations(reader.id, self.crs, self.vertical,
                                                     POINT_SETTINGS)
        request = reader.request(reader.kinds[0], declarations,
                                 dict(zip(inputs.reader_roles([anchor]), [source], strict=True)),
                                 POINT_SETTINGS)
        name = "Taludes Lejanos"
        spec = gis.store.source_input(reader.id, name, files=[anchor], file_prints=prints,
                                      digest=readers.read_content(reader, request),
                                      crs=self.crs, vertical=self.vertical,
                                      settings=POINT_SETTINGS)
        table = read_table(source, encoding="utf-8", separator=";")
        mapping = gis.points.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)
        points, lines, _report = gis.points.points_from_rows(
            table.columns, table.rows, mapping, ",", row_numbers=table.lines)
        with gis.store.ResultWriter(self.project, begin(gis.provenance.IMPORT_POINTS)) as out:
            out.declare_input(spec)
            out.points(name, points)
            out.breaklines(name, lines)
            out.commit(message="Taludes de la prueba de la vista")
        return points, lines

    def _marks(self) -> None:
        """Las curvas, obsoletas (otra equidistancia en el proyecto); el TIN, bloqueado; y
        la segunda rejilla, que falta."""
        params = _module("core.params")
        datasets = _module("core.datasets")
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, INTERVAL, value=2.0, kind="ADOPTADO", source="Plano de prueba",
                         source_kind="document", decided_by="la prueba",
                         reason="Curvas cada 2 m en la prueba de la vista")
            for name, status in (("gis_tin_topo_lejano", "blocked"),
                                 ("gis_dtm_mdt_falta", "missing")):
                datasets.set_status(conn, self.project, self.record(name, conn).uid, status)

    def record(self, name: str, conn: Any = None) -> Any:
        registry = _module("core.datasets.registry")
        if conn is not None:
            return registry.get(conn, name)
        with self.project.read() as reading:
            return registry.get(reading, name)

    def finished_at(self, record: Any) -> str:
        with self.project.read() as conn:
            (found,) = conn.execute("SELECT finished_at FROM gb_operation WHERE uid = ?",
                                    (record.operation_uid,)).fetchone()
        return str(found)

    def operations(self) -> int:
        with self.project.read() as conn:
            return conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0]


class ViewsCase(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la prueba abierto en la sesión."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ps = _module("bl.scene.project_session")
        cls.views = _module("bl.scene.views")
        cls.gis_views = _module("bl.scene.gis_views")
        cls.mesh = _module("bl.scene.mesh")
        cls.gis_mesh = _module("gis.mesh")
        cls.tmp = Path(tempfile.mkdtemp(prefix="gb-t27-"))
        try:
            cls.data = ViewProject(cls.tmp)
            cls.ps.attach(cls.data.project)
        except BaseException:
            cls.tearDownClass()
            raise
        cls.project = cls.data.project
        cls.origin = cls.project.origin

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ps.close()
        blender_ext.load_file()
        blender_ext.unload()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        self.addCleanup(self.unload_all)
        self.ps.take_notices()

    def unload_all(self) -> None:
        uids = {obj.geoblender.dataset_uid for obj in bpy.data.objects
                if obj.geoblender.dataset_uid}
        self.views.unload_datasets(uids)

    # --- Ayudas -----------------------------------------------------------------------------

    def load(self, *names: str, lod: str = "FULL", undo: bool = False) -> set[str]:
        args = ("EXEC_DEFAULT", True) if undo else ("EXEC_DEFAULT",)
        return bpy.ops.geoblender.core_load_into_view(*args, datasets=",".join(names), lod=lod)

    def objects_of(self, name: str) -> list[bpy.types.Object]:
        uid = self.data.record(name).uid
        return [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]

    def only(self, name: str) -> bpy.types.Object:
        (found,) = self.objects_of(name)
        return found

    def world(self, obj: bpy.types.Object) -> np.ndarray:
        """Los vértices de ``obj`` vueltos a absolutas (float64)."""
        return self.mesh.mesh_vertices_world(obj.data, self.origin)

    def assertNear(self, got: np.ndarray, expected: np.ndarray) -> float:
        self.assertEqual(got.shape, expected.shape)
        error = float(np.max(np.abs(got - expected)))
        self.assertLessEqual(error, LIMIT_M)
        return error


class ViewsTest(ViewsCase):
    def test_roundtrip_identity_and_marks(self) -> None:
        """RF-006-19, RF-006-29 (plan §5.6.7): la rejilla, el TIN, los puntos, las líneas de
        rotura y las curvas a ±8 km vuelven a absolutas a ≤ 0,5 mm, con matriz identidad y sus
        triángulos o aristas; cada objeto con su tipo, su dato, su proyecto, su hash, su
        estado (el TIN, bloqueado), la fecha de su operación y su marca de obsoleto (las
        curvas), con nombre generado, en la colección de su dato dentro de «Datos base /
        Topografía»; el ancla con las esquinas de la ventana en texto y el recorte de cada
        Vista 3D que cubre lo cargado (lejano/cercano ≤ 10⁵). Cargar no registra ninguna
        operación ni cambia ningún fichero del proyecto."""
        data = self.data
        names = ("gis_dtm_mdt_lejano", "gis_tin_topo_lejano", "gis_pts_taludes_lejanos",
                 "gis_brk_taludes_lejanos", "gis_cnt_curvas_lejanas")
        before, operations = project_files(data.root), data.operations()
        self.assertEqual(self.load(*names), {"FINISHED"})
        self.assertEqual((project_files(data.root), data.operations()), (before, operations))
        grid = self.gis_mesh.surface_mesh_from_raster(data.raster)
        lines = [line.xyz for line in data.lines]
        rings = [line.xyz for line in data.contours]
        expected = {
            "gis_dtm_mdt_lejano": ("DTM", grid.vertices, grid.faces, None),
            "gis_tin_topo_lejano": ("TIN", data.tin.vertices, data.tin.faces, None),
            "gis_pts_taludes_lejanos": ("POINTS", data.points.xyz, None, None),
            "gis_brk_taludes_lejanos": ("BREAKLINES", np.vstack(lines), None,
                                        [len(xyz) - 1 for xyz in lines]),
            "gis_cnt_curvas_lejanas": ("CONTOURS", np.vstack(rings), None, [2, 4]),
        }
        errors, reach, corners = [], [], []
        for name, (kind, vertices, faces, edges) in expected.items():
            with self.subTest(dato=name):
                record = data.record(name)
                obj = self.only(name)
                self.assertEqual([list(row) for row in obj.matrix_world],
                                 [[float(i == j) for j in range(4)] for i in range(4)])
                errors.append(self.assertNear(self.world(obj), vertices))
                local = self.mesh.mesh_vertices_local(obj.data)
                reach.append(float(np.min(np.max(np.abs(local[:, :2]), axis=0))))
                corners.extend((local.min(axis=0), local.max(axis=0)))
                if faces is not None:
                    got = self.mesh.mesh_triangles(obj.data)
                    self.assertTrue(np.array_equal(got, faces))
                if edges is not None:
                    self.assertEqual(len(obj.data.edges), sum(edges))
                    self.assertEqual(len(obj.data.polygons), 0)
                props = obj.geoblender
                self.assertEqual(
                    {key: getattr(props, key) for key in OBJECT_PROPS},
                    {"kind": kind, "dataset_uid": record.uid,
                     "project_uid": self.project.uid,
                     "content_sha256": record.content_sha256,
                     "stale": name == "gis_cnt_curvas_lejanas",
                     "status": STATUS[str(record.status)],
                     "date": data.finished_at(record)})
                (collection,) = obj.users_collection
                self.assertEqual(collection.name, obj.name)
                self.assertIn("[VIGENTE" if record.status == "current" else "[BLOQUEADO",
                              obj.name)
                self.assertEqual(self.views.collection_path(collection),
                                 ["Datos base", "Topografía", obj.name])
        self.assertIn("[VIGENTE · OBSOLETO]", self.only("gis_cnt_curvas_lejanas").name)
        self.assertGreaterEqual(min(reach), FAR_M)  # cada dato, a ±8 km del origen en X e Y
        print(f"\nRF-006-19: error máximo de la ida y vuelta a ±8 km: {max(errors) * 1000:.4f} mm"
              f" (≤ {LIMIT_M * 1000:.1f} mm)")
        self.assert_anchor()
        self.assert_clip(np.min(corners, axis=0), np.max(corners, axis=0))

    def assert_anchor(self) -> None:
        anchors = [obj for obj in bpy.data.objects
                   if obj.geoblender.kind == "PROJECT_ANCHOR"]
        self.assertEqual(len(anchors), 1)
        (anchor,) = anchors
        window = self.project.window
        self.assertEqual((anchor.type, anchor.geoblender.project_uid),
                         ("EMPTY", self.project.uid))
        self.assertEqual(tuple(anchor.location), (0.0, 0.0, 0.0))
        self.assertEqual([float(anchor[f"window_{key}"]) for key in ("xmin", "ymin", "xmax",
                                                                       "ymax")],
                         [window.xmin, window.ymin, window.xmax, window.ymax])
        self.assertIsInstance(anchor["window_xmin"], str)
        self.assertEqual(anchor["geoorigin"], "700000 4400000 0")
        self.assertEqual(anchor["crs"], "EPSG:25830 + EPSG:5782")
        self.assertEqual(self.views.collection_path(anchor.users_collection[0]), ["Proyecto"])

    def assert_clip(self, low: np.ndarray, high: np.ndarray) -> None:
        """Desde el ojo de cada Vista 3D, la esquina más lejana de lo cargado queda dentro del
        recorte (también en ortográfica, que recorta a ±clip_end/2) y lejano/cercano ≤ 10⁵."""
        spaces = [area.spaces.active for screen in bpy.data.screens for area in screen.areas
                  if area.type == "VIEW_3D"]
        self.assertGreater(len(spaces), 0)
        box = [Vector((x, y, z)) for x in (low[0], high[0]) for y in (low[1], high[1])
               for z in (low[2], high[2])]
        for space in spaces:
            rv3d = space.region_3d
            eye = rv3d.view_location + rv3d.view_rotation @ Vector((0.0, 0.0,
                                                                    rv3d.view_distance))
            far = max((corner - eye).length for corner in box)
            self.assertGreaterEqual(space.clip_end, 2.0 * far)
            self.assertLessEqual(space.clip_end / space.clip_start, CLIP_RATIO_MAX * 1.000001)

    def test_missing_is_not_loaded_and_blocked_is_marked(self) -> None:
        """Plan §5.6.7: de un dato que falta se avisa y no se carga; uno bloqueado se carga
        con su marca; uno que el proyecto no tiene es un error; los demás se cargan."""
        outcome = self.views.load_datasets(
            bpy.context, self.project,
            ["gis_dtm_mdt_falta", "gis_tin_topo_lejano", "gis_nada"])
        self.assertEqual(outcome.loaded, ("gis_tin_topo_lejano",))
        self.assertEqual(self.objects_of("gis_dtm_mdt_falta"), [])
        self.assertEqual(self.only("gis_tin_topo_lejano").geoblender.status, "BLOCKED")
        self.assertEqual(len(outcome.notes), 1)
        self.assertIn("gis_dtm_mdt_falta", outcome.notes[0])
        self.assertIn("falta", outcome.notes[0])
        self.assertEqual(len(outcome.errors), 1)
        self.assertIn("gis_nada", outcome.errors[0])

    def test_inverted_mesh_is_not_shown(self) -> None:
        """RF-006-21: si la malla de una superficie sale con las caras al revés, no se
        muestra: ni objeto ni malla, y el error dice cuántas caras fallan y la diferencia de
        volumen."""
        real = self.gis_views.surface_mesh_from_tin
        meshes = len(bpy.data.meshes)

        def inverted(tin: Any) -> Any:
            arrays = real(tin)
            return type(arrays)(arrays.vertices, np.ascontiguousarray(arrays.faces[:, ::-1]))

        with mock.patch.object(self.gis_views, "surface_mesh_from_tin", inverted):
            outcome = self.views.load_datasets(bpy.context, self.project,
                                               ["gis_tin_topo_lejano"])
        self.assertEqual((outcome.loaded, self.objects_of("gis_tin_topo_lejano")), ((), []))
        self.assertEqual(len(bpy.data.meshes), meshes)
        (error,) = outcome.errors
        self.assertIn("no es válida", error)
        self.assertIn("4 de sus 4 caras", error)

    def test_levels_of_detail(self) -> None:
        """RF-006-22: la rejilla de 1 m se carga en sus versiones de 2 y 5 m (media por área,
        ``gis.mesh.lod_rasters``) y se pasa de una a otra (y a la de cálculo) con un solo
        objeto del dato; el fichero de la rejilla de cálculo no cambia."""
        data = self.data
        name = "gis_dtm_mdt_lejano"
        before = project_files(data.root)
        levels = self.gis_mesh.lod_rasters(data.raster)
        self.assertEqual(sorted(levels), [2.0, 5.0])
        for lod, raster in (("LOD1", levels[2.0]), ("LOD2", levels[5.0]),
                            ("FULL", data.raster)):
            with self.subTest(nivel=lod):
                self.assertEqual(self.load(name, lod=lod), {"FINISHED"})
                expected = self.gis_mesh.surface_mesh_from_raster(raster)
                obj = self.only(name)
                self.assertNear(self.world(obj), expected.vertices)
                self.assertTrue(np.array_equal(self.mesh.mesh_triangles(obj.data),
                                               expected.faces))
        self.assertEqual(project_files(data.root), before)

    def test_unload_removes_objects_and_meshes_only(self) -> None:
        """RF-006-20: descargar los datos de la selección quita sus objetos, sus mallas y sus
        colecciones vacías; no registra ninguna operación ni cambia ningún fichero del
        proyecto, y el ancla sigue."""
        data = self.data
        meshes = len(bpy.data.meshes)
        collections = len(bpy.data.collections)
        before, operations = project_files(data.root), data.operations()
        self.assertEqual(self.load("gis_dtm_mdt_lejano", "gis_pts_taludes_lejanos"),
                         {"FINISHED"})
        self.assertEqual(len(bpy.data.meshes), meshes + 2)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(bool(obj.geoblender.dataset_uid))
        self.assertEqual(bpy.ops.geoblender.core_unload_from_view("EXEC_DEFAULT"),
                         {"FINISHED"})
        self.assertEqual([obj.name for obj in bpy.data.objects if obj.geoblender.dataset_uid],
                         [])
        self.assertEqual(len(bpy.data.meshes), meshes)
        keys = [str(item.get(self.views.KEY_PROPERTY, "")) for item in bpy.data.collections]
        self.assertEqual([key for key in keys if key], ["project"])  # «Proyecto», el ancla
        self.assertGreaterEqual(len(bpy.data.collections), collections)
        self.assertEqual((project_files(data.root), data.operations()), (before, operations))

    def test_undo_after_loading_undoes_only_the_view(self) -> None:
        """RF-006-20 (plan §5.3.5): Ctrl+Z tras cargar quita lo cargado de la vista; el
        proyecto sigue abierto y sin cambios."""
        data = self.data
        before = project_files(data.root)
        bpy.ops.ed.undo_push(message="antes de cargar")
        self.assertEqual(self.load("gis_tin_topo_lejano", undo=True), {"FINISHED"})
        self.assertEqual(len(self.objects_of("gis_tin_topo_lejano")), 1)
        bpy.ops.ed.undo()
        self.assertEqual(self.objects_of("gis_tin_topo_lejano"), [])
        self.assertIs(self.ps.current(), self.project)
        self.assertEqual(project_files(data.root), before)


class ViewRegistrationTest(unittest.TestCase):
    """La extensión deshabilitada y fuera de ``sys.modules`` al empezar y al terminar."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_register_and_unregister_leave_blender_as_it_was(self) -> None:
        """RF-006-29, principio 8: habilitar pone ``Object.geoblender``
        (``GEOBLENDER_PG_core_object``, sin propiedades flotantes), los dos operadores de la
        vista con ``UNDO`` y los cargadores de la topografía; deshabilitar lo quita todo y
        deja la huella de Blender como al principio de la sesión de pruebas."""
        blender_ext.enable()
        prop = _module("bl.props.core").OBJECT_PROPERTY
        rna = bpy.types.Object.bl_rna.properties[prop]
        self.assertEqual((rna.type, rna.fixed_type.identifier),
                         ("POINTER", "GEOBLENDER_PG_core_object"))
        group = rna.fixed_type.properties
        own = [key for key in group.keys() if key not in ("rna_type", "name")]
        self.assertEqual(sorted(own), sorted(OBJECT_PROPS))
        self.assertEqual([key for key in group.keys() if group[key].type == "FLOAT"], [])
        kinds = [item.identifier for item in group["kind"].enum_items]
        self.assertEqual(kinds[:9], ["NONE", "PROJECT_ANCHOR", "DTM", "TIN", "POINTS",
                                     "BREAKLINES", "CONTOURS", "BOUNDARY", "DRILLHOLES"])
        ops = _module("bl.ops.core")
        for cls in (ops.GEOBLENDER_OT_core_load_into_view,
                    ops.GEOBLENDER_OT_core_unload_from_view):
            self.assertTrue(cls.is_registered)
            self.assertEqual(cls.bl_options, {"REGISTER", "UNDO"})
        views = _module("bl.scene.views")
        self.assertEqual(sorted(views.loaders()),
                         ["gis_brk_", "gis_cnt_", "gis_dtm_", "gis_pts_", "gis_src_",
                          "gis_tin_"])
        blender_ext.disable()
        self.assertFalse(hasattr(bpy.types.Object, prop))
        self.assertEqual(views.loaders(), {})
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()

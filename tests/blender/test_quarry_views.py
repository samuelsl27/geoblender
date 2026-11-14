# SPDX-License-Identifier: GPL-3.0-or-later
"""El resumen, la clasificación y la barra N de la cantera con dos superficies (spec 014, T22;
HU-014-3, HU-014-4; RF-014-15 a RF-014-18; plan 014 §5.1, §5.2.3, §5.5; comprobación manual M3 y
M4).

**El resumen** de «Cantera con dos superficies…» (``bl.ui.des_panels.show_summary``) enseña, además
del orden y de las cotas de cada superficie, la excavación de la explotación en m³ y ha, el
desdoblado y el relleno de restauración en m³, **la clasificación** con el área de cada clase en ha
(desdoblado, relleno de restauración y sin diferencia, con el espesor mínimo que la separa), el modo
«explotación hasta la final» y los avisos (el de desdoblado sobre terreno sin explotar con sus
zonas, en ámbar, y lo que pasó a la explotación con el modo). **Los cargadores** de
``bl.scene.des_views`` cargan como objetos ``DESIGN`` las dos superficies (``des_exp_`` y
``des_fin_``), sus envolventes (``des_xen_`` y ``des_fen_``) y la clasificación (``des_cls_``), esta
sobre la superficie final con **un color por clase** (gris, naranja y verde). **La barra N
«Diseño»** enseña la ficha de cada una: su título, su estado, los ajustes, los perfiles de cada
superficie, la superficie de partida, las capas, los parámetros, las semillas de cada superficie,
las restricciones, la leyenda (la de la clasificación) y las cifras registradas.

Un proyecto por clase, como el de ``test_quarry_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y
V02, el límite legal de (4, 4) a (52, 52) con 2 m hacia dentro, el perímetro de (2, 10) a (56, 56),
una zona sin corte, dos sectores con la búsqueda cerrada, la ladera ``100 + 0,25·y + 0,0625·x``, los
perfiles ``EXPL_10_60_6`` y ``REST_5_35_6`` y las capas de fondos, corredores y zonas de relleno),
con el área mínima del aviso de desdoblado en 0,01 ha (la ventana entera tiene 0,36 ha). La cantera
«Corta»: la final con ``REST_5_35_6`` y semillas en la coronación y las zonas a sostener; la
explotación con ``EXPL_10_60_6`` y semillas en toda la ladera (no excava: queda sobre el terreno sin
explotar, y la final, por debajo: el desdoblado del error 60). Las pruebas, en el orden de sus
letras sobre el mismo estado:

- RF-014-15, RF-014-16 (a): las familias de la cantera tienen su cargador ``DESIGN`` con su nombre
  (las tablas, no), en los dos idiomas.
- RF-014-15 a RF-014-18 (b; M3, M4): el resumen sin el modo: la clasificación en m³ y ha (los de la
  clasificación calculada), «explotación hasta la final: no» y el aviso de desdoblado en ámbar con
  sus zonas; con «todas las zonas avisadas», lo que pasa a la explotación y sin la línea del «no»;
  en inglés; Crear.
- RF-014-16 (c; M3): cargar las dos superficies da sus objetos con las cotas registradas.
- RF-014-15 (d; M3): cargar la clasificación da un objeto sobre la superficie final, con un vértice
  en cada celda clasificada, la clase de cada cara (la de la mayoría de sus vértices) y su color.
- RF-014-16 (e; M3): la barra N de la superficie de explotación, de la final, de una envolvente y de
  la clasificación (con su leyenda), y «Elemento activo» con las mismas líneas.
- T45 de la 013 (f): ningún diálogo propone una rejilla de la cantera como terreno.
- Principio 8 (z): desactivar Geoblender quita los cargadores de la cantera.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

KIND = "DESIGN"
PANEL = "GEOBLENDER_PT_des_design"
VIEW_PROPERTY = "geoblender_design"
QUARRY = "geoblender.des_design_quarry"
LIMIT = "geoblender.des_create_limit_from_perimeter"
REASON = "Prueba de las vistas de la cantera"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 10.0, 56.0, 56.0)
NO_CUT = (20.0, 20.0, 30.0, 30.0)
SECTORS = {"Sector oeste": (0.0, 0.0, 30.0, 60.0), "Sector este": (30.0, 0.0, 60.0, 60.0)}
CLOSED_AT = "2026-11-12T10:00:00Z"
LAYERS_TYPE = "gis.test_quarry_views"
FLOORS_LAYER = "gis_fea_fondos"
FLOOR_BOX = (12.0, 16.0, 24.0, 40.0)
CORRIDORS_LAYER = "gis_fea_corredores"
CORRIDOR_AXIS = ((36.0, 20.0), (36.0, 44.0))
FILL_LAYER = "gis_fea_relleno"
FILL_BOX = (40.0, 30.0, 48.0, 46.0)
EXPL, REST = "EXPL_10_60_6", "REST_5_35_6"
NAME = "Corta"
MIN_AREA_KEY = "des.quarry.unsplit_min_area_ha"
MIN_AREA_HA = 0.01
FAMILIES = {"exp": "Exploitation surface", "fin": "Final surface",
            "xen": "Exploitation envelope", "fen": "Final envelope", "cls": "Classification"}
"""Las rejillas de la cantera que se cargan en la vista, con el ``msgid`` de su nombre."""
LABELS_ES = {"exp": "Superficie de explotación", "fin": "Superficie final",
             "xen": "Envolvente de explotación", "fen": "Envolvente final",
             "cls": "Clasificación"}
TABLES = ("bmt", "qrp")
"""Las tablas de la cantera, que no se cargan en la vista."""
CLASS_COLORS = {0: "gris", 1: "naranja", 2: "verde"}
"""El color de cada clase en la leyenda (0 sin diferencia, 1 desdoblado, 2 relleno)."""
LEGEND = ["0 · gris: sin diferencia", "1 · naranja: desdoblado",
          "2 · verde: relleno de restauración"]


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def path(points: tuple[tuple[float, float], ...]) -> np.ndarray:
    """El camino absoluto de los puntos locales ``points``."""
    return np.array([(WEST + x, SOUTH + y) for x, y in points], dtype=np.float64)


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (fila 0 al norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    x, y = np.meshgrid(STEP_M * index + STEP_M / 2, SIZE_M - (STEP_M * index + STEP_M / 2))
    return 100.0 + 0.25 * y + 0.0625 * x


class QuarryViewsTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera, para toda la clase (las pruebas,
    en el orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t22-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.des_ops = _module("bl.ops.des")
        cls.commands = _module("bl.ui.commands")
        cls.panels = _module("bl.ui.des_panels")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.views = _module("bl.scene.views")
        cls.des_views = _module("bl.scene.des_views")
        cls.mesh = _module("bl.scene.mesh")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        cls.ui_i18n = _module("bl.ui.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="cantera",
                                                      title="Cantera", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.declare_sectors()
        cls.close_search("sector_1")
        cls.close_search("sector_2")
        cls.ground = cls.write_grid("Ladera", ground())
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.write_layer(FLOORS_LAYER, "polygon", ((ring(FLOOR_BOX),),), {"cota": 100.0})
        cls.write_layer(CORRIDORS_LAYER, "line", ((path(CORRIDOR_AXIS),),),
                        {"ancho": 4.0, "cota": 104.0})
        cls.write_layer(FILL_LAYER, "polygon", ((ring(FILL_BOX),),), {})
        params = _module("core.params").ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:  # zonas de 0,01 ha: caben en la ventana
            params.create(conn, MIN_AREA_KEY, MIN_AREA_HA, kind="ADOPTADO",
                          source="Criterio de la prueba", source_kind="person", decided_by=PERSON,
                          reason=REASON)
        cls.project.refresh_header()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        for name, (height, face, berm) in ((EXPL, ("10", "60", "6")), (REST, ("5", "35", "6"))):
            assert bpy.ops.geoblender.des_save_bench_profile(
                name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
                scope="PROJECT", height=height, face=face, berm=berm, anchor="125") == {"FINISHED"}
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)
        cls.names = {family: cls.dprov.dataset_name(family, NAME)
                     for family in (*FAMILIES, *TABLES)}

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y una zona sin corte."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 12), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.NO_CUT, "Sin corte", NO_CUT)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                   srs_id=cls.project.record.crs_epsg)

    @classmethod
    def declare_sectors(cls) -> None:
        """Los dos sectores de búsqueda (``core_sector``)."""
        sectors = tuple(
            cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name, (ring(box),))
            for index, (name, box) in enumerate(SECTORS.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str) -> None:
        """Cierra la búsqueda de intocables del sector ``code``, como la orden de la 012."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, code,
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_layer(cls, name: str, kind: str, entity: tuple[tuple[np.ndarray, ...], ...],
                    numbers: dict[str, float]) -> None:
        """Una capa ``gis_fea_…`` de una entidad con el campo ``nombre`` y los campos numéricos
        ``numbers`` (``DOUBLE``), como la deja la importación de la 006."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
                   *(vector.FieldColumn(field, field, "DOUBLE") for field in numbers))
        values = {"nombre": ("Entidad 1",), **{field: (value,) for field, value in numbers.items()}}
        layer = vector.FeatureLayer(kind, (1,), (entity,), columns, values)
        rows = gis_store.feature_rows(layer, srs)
        names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f"geom {layer.geometry_type}, {names})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de prueba de la cantera")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto de la ventana con ``values``; el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no sigue

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def files(self) -> list[str]:
        """Los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(item.relative_to(root)) for item in root.rglob("*")
                      if item.is_file() and item.suffix != ".gpkg-journal")

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo, como desde un guion: la final con ``REST_5_35_6`` y semillas en
        la coronación; la explotación con ``EXPL_10_60_6`` y semillas en toda la ladera (dentro del
        dominio por defecto, con su confirmación: caen fuera de la coronación, T43); los fondos, el
        corredor de cota fija y las zonas de relleno."""
        return {"name": NAME, "start": self.ground, "final_profile": REST,
                "exploitation_profile": EXPL, "exploitation_seeds": "SURFACE",
                "exploitation_surface": self.ground, "exploitation_zone": "domain",
                "floors_layer": FLOORS_LAYER, "corridors_layer": CORRIDORS_LAYER,
                "corridors_level": "FIXED", "fill_layer": FILL_LAYER, "in_steps": False,
                "confirm_outside": True, **values}

    def calculate(self, **values: Any) -> Any:
        """«Calcular» desde un guion: el cálculo abierto, con su resumen en la vista."""
        found = bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", **self.form(**values))
        self.assertEqual(found, {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    def uid(self, family: str) -> str:
        """El uid del dato vivo de la familia ``family`` de la cantera."""
        (found,) = self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'",
                             self.names[family])
        return str(found[0])

    def read(self, family: str) -> np.ndarray:
        """Las cotas (o los códigos) de la rejilla ``family`` de la cantera, releídas."""
        return self.surfaces.read_surface(self.project, self.names[family],
                                          version_uid=self.v01.uid).values

    def loaded(self, family: str) -> Any:
        """El objeto de la vista de la rejilla ``family`` (lo carga si no está)."""
        uid = self.uid(family)
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        if not found:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
            found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        self.assertEqual(len(found), 1)
        return found[0]

    def cells(self, obj: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """La fila y la columna de la celda de cada vértice de ``obj`` y sus vértices absolutos
        (comprobado que cada uno está en el centro de una celda)."""
        world = self.mesh.mesh_vertices_world(obj.data, self.project.origin)
        grid = _module("gis.grid").project_grid(self.project.record.window, STEP_M)
        columns = (world[:, 0] - grid.west) / grid.dx - 0.5
        rows = (grid.north - world[:, 1]) / grid.dy - 0.5
        np.testing.assert_allclose(columns, np.rint(columns), atol=1e-6)  # centros de celda
        np.testing.assert_allclose(rows, np.rint(rows), atol=1e-6)
        return np.rint(rows).astype(int), np.rint(columns).astype(int), world

    def choose(self, obj: Any) -> None:
        """Selecciona y activa ``obj`` y lee su ficha, como Blender al cambiar el objeto activo."""
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()

    def texts(self) -> list[str]:
        return [row.name for row in self.view.item]

    def kinds(self) -> dict[str, str]:
        return {row.name: row.kind for row in self.view.item}

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_loaders_of_the_quarry_grids(self) -> None:
        """RF-014-15, RF-014-16 (plan §5.1, §5.2.3): las dos superficies, sus envolventes y la
        clasificación de una cantera tienen su cargador, del tipo ``DESIGN`` y con un nombre cada
        una (el de su objeto en la vista, con su español); las bermas y el informe, tablas, no se
        cargan; la clasificación tiene su leyenda, un color por clase."""
        labels = set()
        for family, label in FAMILIES.items():
            with self.subTest(familia=family):
                prefix = f"des_{family}_"
                loader = self.views.loader_for(f"{prefix}corta")
                self.assertIsNotNone(loader, prefix)
                self.assertEqual((loader.prefix, loader.kind, loader.label), (prefix, KIND, label))
                self.assertEqual(self.i18n.translate("es", label), LABELS_ES[family])
                labels.add(label)
        self.assertEqual(len(labels), len(FAMILIES))  # dos objetos de la cantera no chocan
        self.assertEqual(len({label for _family, label in self.des_views.LOADERS}),
                         len(self.des_views.LOADERS))
        for family in TABLES:
            self.assertIsNone(self.views.loader_for(f"des_{family}_corta"))
        codes = [item[0] for item in self.des_views.CLASS_LEGEND]
        self.assertEqual(codes, [0, 1, 2])
        legend = self.des_views.CLASS_LEGEND
        self.assertEqual([self.i18n.translate("es", item[2]) for item in legend], LEGEND)
        self.assertEqual(self.i18n.untranslated([item[2] for item in self.des_views.CLASS_LEGEND]),
                         [])
        colors = {code: tuple(color) for code, color, _label in self.des_views.CLASS_LEGEND}
        self.assertEqual(len(set(colors.values())), 3)  # un color por clase
        gray = colors[0]
        self.assertTrue(gray[0] == gray[1] == gray[2])  # sin diferencia, gris
        self.assertGreater(colors[1][0], colors[1][2])  # desdoblado, naranja
        self.assertGreater(colors[2][1], max(colors[2][0], colors[2][2]))  # relleno, verde

    def test_b_the_summary_with_the_classification_and_the_mode(self) -> None:
        """RF-014-15 a RF-014-18 (plan §5.5; M3, M4): el resumen de la cantera sin el modo enseña,
        tras el orden y las cotas, la excavación de la explotación en m³ y ha, el desdoblado y el
        relleno en m³, la clasificación con el área de cada clase en ha y su espesor mínimo (las
        cifras de la clasificación calculada), «Explotación hasta la final: no» y los avisos —el de
        desdoblado sobre terreno sin explotar con sus zonas, en ámbar—; con «todas las zonas
        avisadas», lo que pasa a la explotación y no el «no». En inglés, igual. Crear la segunda."""
        fmt = self.i18n.format_number
        format_value = _module("core.params").format_value

        def expected(held: Any, language: str) -> list[tuple[str, bool]]:
            tr = self.i18n.tr
            outcome = held.outcome
            total = outcome.classes.total
            order = tr("Final surface first")
            final, exploitation = total.levels("final"), total.levels("exploitation")
            lines = [
                (tr("Order of the design: {order} · the order rule changed {cells} cells",
                    order=order, cells=fmt(outcome.adjusted, 0)), False),
                (tr("Final surface: elevations {low} to {high} m", low=fmt(final[0], 1),
                    high=fmt(final[1], 1)), False),
                (tr("Exploitation surface: elevations {low} to {high} m · excavation {cut} m³ in "
                    "{area} ha", low=fmt(exploitation[0], 1), high=fmt(exploitation[1], 1),
                    cut=fmt(total.exp_cut_m3, 0), area=fmt(total.exp_cut_area_ha, 2)), False),
                (tr("Unsplit {unsplit} m³ · restoration fill {fill} m³",
                    unsplit=fmt(total.unsplit_m3, 0), fill=fmt(total.fill_m3, 0)), False),
                (tr("Classification (minimum thickness {thickness} m): unsplit {unsplit} ha · "
                    "restoration fill {fill} ha · no difference {none} ha",
                    thickness=format_value(outcome.classes.min_thickness_m, language),
                    unsplit=fmt(total.area_ha("unsplit"), 2), fill=fmt(total.area_ha("fill"), 2),
                    none=fmt(total.area_ha("none"), 2)), False)]
            if outcome.to_final is None:
                lines.append((tr("Exploitation down to the final surface: no"), False))
            lines += [(notice.text(language), notice.severity == "warning")
                      for notice in held.notices]
            return lines

        held = self.calculate(to_final="NONE")
        self.assertEqual(self.view.summary_title, "Cantera «Corta» en V01")
        shown = self.summary()
        self.assertEqual(shown, expected(held, "es"))
        total = held.outcome.classes.total
        self.assertGreater(total.unsplit_m3, 0.0)  # el desdoblado del error 60 (RF-014-17)
        self.assertGreater(total.fill_m3, 0.0)  # y relleno en su zona (RF-014-15)
        self.assertEqual(total.exp_cut_m3, 0.0)  # la explotación no excava sin el modo
        self.assertIn(("Explotación hasta la final: no", False), shown)
        warning = [text for text, alert in shown
                   if alert and text.startswith("La explotación no llega a la final en ")]
        self.assertEqual(len(warning), 1, shown)
        self.assertIn("«Explotación hasta la final»", warning[0])  # el modo que se ofrece
        zones = held.outcome.unsplit.zones
        self.assertGreater(len(zones), 0)
        self.assertEqual(len([text for text, _alert in shown if text.startswith("Zona ")]),
                         len(zones))  # cada zona, con su área, su volumen y su centro
        classification = shown[4][0]
        self.assertTrue(classification.startswith("Clasificación (espesor mínimo "),
                        classification)
        self.assertEqual(total.cells_of("unsplit") + total.cells_of("fill")
                         + total.cells_of("none") + total.nodata_cells, total.cells)
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.summary(), expected(held, "en"))
        self.assertIn(("Exploitation down to the final surface: no", False), self.summary())
        self.i18n.set_language("es")
        self.des_ops.discard_calculation()

        held = self.calculate(to_final="WARNED")
        shown = self.summary()
        self.assertEqual(shown, expected(held, "es"))
        self.assertIsNotNone(held.outcome.to_final)
        self.assertNotIn(("Explotación hasta la final: no", False), shown)
        moved = [text for text, _alert in shown
                 if text.startswith("«Explotación hasta la final» en ")]
        self.assertEqual(len(moved), 1, shown)
        self.assertGreater(held.outcome.to_final.volume_m3, 0.0)
        self.assertGreater(held.outcome.classes.total.exp_cut_m3, 0.0)  # ahora excava
        self.assertEqual(bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", confirm=True),
                         {"FINISHED"})
        self.assertEqual(self.view.summary_title, "")

    def test_c_the_two_surfaces_in_the_view(self) -> None:
        """RF-014-16 (M3), ADR-0005: «Cargar en la vista» de las dos superficies y de sus
        envolventes da un objeto ``DESIGN`` por rejilla («Superficie de explotación corta · V01
        [VIGENTE]»…), con matriz identidad y un vértice en el centro de cada celda con dato, a la
        cota registrada; la vista no escribe nada en el proyecto."""
        files, operations = self.files(), self.operations()
        for family in ("exp", "fin", "xen", "fen"):
            with self.subTest(familia=family):
                obj = self.loaded(family)
                self.assertEqual(obj.geoblender.kind, KIND)
                self.assertEqual(obj.name, f"{LABELS_ES[family]} corta · V01 [VIGENTE]")
                self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
                self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))
                values = self.read(family)
                rows, columns, world = self.cells(obj)
                shown = np.zeros(values.shape, dtype=bool)
                shown[rows, columns] = True
                self.assertTrue(np.array_equal(shown, np.isfinite(values)))
                np.testing.assert_allclose(world[:, 2], values[rows, columns], atol=1e-4)
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_d_the_classification_in_the_view_with_a_color_per_class(self) -> None:
        """RF-014-15 (plan §5.1; M3): «Cargar en la vista» de la clasificación da un objeto
        ``DESIGN`` «Clasificación corta · V01 [VIGENTE]» **sobre la superficie final**: un vértice
        en el centro de cada celda clasificada (y de ninguna otra) a la cota de la final; cada cara,
        la clase de la mayoría de sus tres vértices (``gb_class``) y su color (``gb_color``, el de
        la leyenda), con el material de la clasificación; la vista no escribe nada."""
        files, operations = self.files(), self.operations()
        obj = self.loaded("cls")
        self.assertEqual(obj.name, "Clasificación corta · V01 [VIGENTE]")
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        classes, final = self.read("cls"), self.read("fin")
        rows, columns, world = self.cells(obj)
        shown = np.zeros(classes.shape, dtype=bool)
        shown[rows, columns] = True
        self.assertTrue(np.array_equal(shown, np.isfinite(classes)))
        np.testing.assert_allclose(world[:, 2], final[rows, columns], atol=1e-4)
        mesh = obj.data
        triangles = self.mesh.mesh_triangles(mesh)
        wanted = np.median(classes[rows, columns][triangles], axis=1).astype(int)
        found = np.empty(len(mesh.polygons), dtype=np.intc)
        attribute = mesh.attributes["gb_class"]
        self.assertEqual((attribute.domain, attribute.data_type), ("FACE", "INT"))
        attribute.data.foreach_get("value", found)
        self.assertTrue(np.array_equal(found, wanted))
        self.assertGreaterEqual(len(set(found.tolist())), 2)  # más de una clase en la vista
        attribute = mesh.attributes["gb_color"]
        self.assertEqual((attribute.domain, attribute.data_type), ("FACE", "FLOAT_COLOR"))
        colors = np.empty(len(mesh.polygons) * 4, dtype=np.float32)
        attribute.data.foreach_get("color", colors)
        palette = {code: np.asarray(color, dtype=np.float32)
                   for code, color, _label in self.des_views.CLASS_LEGEND}
        np.testing.assert_allclose(colors.reshape(-1, 4),
                                   np.array([palette[int(code)] for code in found]), atol=1e-6)
        self.assertEqual([item.name for item in mesh.materials],
                         [self.des_views.CLASS_MATERIAL])
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_e_the_side_panel_of_the_quarry_grids(self) -> None:
        """RF-014-16 (M3), RF-010-06: seleccionar la superficie de explotación lee su ficha y la
        barra N «Diseño» enseña su título, «Al día», los ajustes de la cantera, los perfiles de cada
        superficie, la superficie de partida, las capas con sus campos, los parámetros, las semillas
        de cada superficie y el dominio (el recinto), las restricciones aplicadas y sus cifras
        registradas con su insignia (todas las de la operación), sin la envolvente de la 013; la de
        la final, la de una envolvente y la de la clasificación, su título, y la de la
        clasificación además su leyenda; «Elemento activo» enseña las mismas líneas."""
        files, operations = self.files(), self.operations()
        panel = getattr(bpy.types, PANEL)
        obj = self.loaded("exp")
        self.choose(obj)
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((self.view.item_uid, self.view.item_found), (self.uid("exp"), True))
        self.assertEqual(self.view.item_title, "Superficie de explotación · Corta")
        texts, kinds = self.texts(), self.kinds()
        self.assertEqual(texts[0], "Al día")
        settings = [text for text in texts if text.startswith("Ajustes:")]
        self.assertEqual(len(settings), 1, texts)
        for part in ("Orden del diseño = Primero la superficie final",
                     "Semillas de la superficie final = Coronación y zonas a sostener",
                     "Explotación hasta la final = Todas las zonas avisadas"):
            self.assertIn(part, settings[0])
        for wanted in ("Perfiles de la superficie final: base REST_5_35_6",
                       "Perfiles de la superficie de explotación: base EXPL_10_60_6",
                       f"Superficie de partida: «{self.ground}»",
                       "Fondos: capa «fondos» · campo «cota»",
                       "Corredores: capa «corredores» · ancho «ancho» · cota «cota»",
                       "Zonas de restauración por relleno: capa «relleno»",
                       "Semillas de la superficie final: Coronación y zonas a sostener",
                       f"Semillas de la superficie de explotación: celdas de «{self.ground}» · "
                       "dominio por defecto",
                       "Dominio de trabajo: el recinto excavable de las máscaras",
                       "Límite legal · Concesión", "Perímetro de actuación · Perímetro"):
            with self.subTest(línea=wanted):
                self.assertIn(wanted, texts)
        for heading in ("Capas", "Parámetros", "Semillas y dominios", "Restricciones aplicadas",
                        "Cifras"):
            self.assertEqual(kinds.get(heading), "heading", heading)
        self.assertNotIn("Leyenda", texts)
        self.assertFalse([text for text in texts if text.startswith("Envolvente")], texts)
        self.assertTrue(any(text.startswith("Ancho del anillo de coronación: 3 [ADO]")
                            for text in texts), texts)
        self.assertTrue(any(text.startswith("Área mínima de una zona de desdoblado que se avisa: "
                                            "0,01 ha [ADO]") for text in texts), texts)
        figures_mod = _module("core.provenance.figures")
        stored = [figures_mod.FigureRecord.from_row(row) for row in self.rows(
            f"SELECT {figures_mod.RECORD_COLUMNS} FROM gb_figure AS f WHERE operation_uid = "
            "(SELECT operation_uid FROM gb_dataset WHERE uid = ?) ORDER BY fid", self.uid("exp"))]
        keys = {figure.key for figure in stored}
        for key in ("des.exp_cut_m3", "des.unsplit_m3", "des.restoration_fill_m3",
                    "des.to_final_m3", "des.unsplit_area_ha"):
            self.assertIn(key, keys)
        shown = [row.name for row in self.view.item if row.kind == "figure"]
        # T61 (lo que vio el H3): la superficie del ámbito, en español («corta, explotación»), y
        # lo guardado igual («exploitation»).
        self.assertEqual(shown, [f"[CAL] {self.dprov.figure_text(figure, language='es')}"
                                 for figure in stored])
        sided = [text for text in shown if "Cota mínima de la superficie" in text]
        self.assertTrue(sided, shown)
        self.assertTrue(any(", explotación = " in text for text in sided), sided)
        self.assertTrue(any(", final = " in text for text in sided), sided)
        self.assertFalse([text for text in shown if "exploitation" in text], shown)
        self.assertIn("exploitation", {figure.scope.get("surface") for figure in stored})
        obj = self.loaded("exp")  # las cifras de su objeto, igual (Object.geoblender.figures)
        labels = [item.label for item in obj.geoblender.figures]
        self.assertTrue(any(label.endswith(", explotación") for label in labels), labels)
        self.assertFalse([label for label in labels if "exploitation" in label], labels)
        joined = " ".join(draw(panel, bpy.context).texts())
        self.assertIn("Superficie de explotación · Corta", joined)

        manager = bpy.context.window_manager
        wanted = [text for text in texts if self.kinds()[text] != "figure"]
        wanted = wanted[:wanted.index("Cifras")]
        self.assertTrue(self.view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(manager, self.view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(wanted):], wanted)

        for family, title in (("fin", "Superficie final · Corta"),
                              ("xen", "Envolvente de explotación · Corta"),
                              ("cls", "Clasificación · Corta")):
            with self.subTest(familia=family):
                self.choose(self.loaded(family))
                self.assertEqual(self.view.item_title, title)
                self.assertIn("Fondos: capa «fondos» · campo «cota»", self.texts())
        texts = self.texts()
        start = texts.index("Leyenda")
        self.assertEqual(self.kinds()["Leyenda"], "heading")
        self.assertEqual(texts[start + 1:start + 4], LEGEND)
        self.i18n.set_language("en")
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertEqual(self.view.item_title, "Classification · Corta")
        self.assertIn("Legend", self.texts())
        self.assertIn("Profiles of the exploitation surface: base EXPL_10_60_6", self.texts())
        self.i18n.set_language("es")
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_f_no_dialog_proposes_a_quarry_grid_as_the_ground(self) -> None:
        """T45 de la 013 (plan 014 §5.3.3): con las rejillas de la cantera en la versión activa
        (las primeras de la lista de superficies), el diálogo de «Límite desde el perímetro…»
        propone como superficie de partida la ladera, no una rejilla de la cantera. T61 (lo que
        vio el H3): las rejillas de **códigos** (la clasificación, el recinto excavable y la
        rejilla de clases de las máscaras) no son cotas: no están en la lista de superficies (la
        de partida, la de las semillas…) ni en la de anclas, y la primera ya no es la
        clasificación."""
        self.panels.refresh_choices(self.project)
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        anchors = [item[0] for item in self.panels.anchor_items(None, None)]
        for family in FAMILIES:
            with self.subTest(familia=family):
                if family == "cls":
                    self.assertNotIn(self.names[family], listed)
                    self.assertNotIn(self.names[family], anchors)
                else:
                    self.assertIn(self.names[family], listed)
        families = self.dprov.FAMILIES_BY_CODE  # (los prefijos de las rejillas de códigos)
        codes = [name for name in (*listed, *anchors)
                 if name.startswith((families["cls"].prefix, families["rcn"].prefix,
                                     "gis_msk"))]
        self.assertEqual(codes, [])
        self.assertTrue(self.rows("SELECT uid FROM gb_dataset WHERE name = 'gis_msk'"))
        self.assertIsNone(self.panels.surface_choice(self.names["cls"]))
        self.assertNotEqual(listed[0], self.ground)  # una de la cantera va antes
        self.assertFalse(listed[0].startswith(families["cls"].prefix))
        for obj in bpy.data.objects:
            obj.select_set(False)
        cls = self.commands.registered_class(LIMIT)
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=bpy.context.window_manager.windows[0], selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fake = operator_self(cls, report=lambda kind, text: None, name="", surface="",
                             confirm=False, in_steps=False,
                             properties=SimpleNamespace(is_property_set=lambda name: False))
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(fake.surface, self.ground)

    def test_g_load_into_the_view_names_each_grid_with_its_quarry(self) -> None:
        """RF-014-15, RF-014-16 (T61; lo que vio el H3 en «Cargar en la vista…», en una captura
        reducida: «Superficie final [VIGENTE]»; recortada, decía «Superficie final cantera
        [VIGENTE]»): el nombre de cada rejilla de una cantera en la lista de «Cargar en la vista…»
        lleva el nombre de la cantera, también la superficie final, así que dos canteras se
        distinguen."""
        names = {}
        for family in FAMILIES:
            (row,) = self.rows("SELECT name FROM gb_dataset WHERE uid = ?", self.uid(family))
            record = SimpleNamespace(name=row[0], status="current")
            other = SimpleNamespace(name=f"{row[0]}_b", status="current")
            loader = self.views.loader_for(record.name)
            names[family] = self.views.view_name(loader, record, stale=False)
            with self.subTest(familia=family):
                self.assertEqual(names[family], f"{LABELS_ES[family]} corta [VIGENTE]")
                self.assertNotEqual(self.views.view_name(loader, other, stale=False),
                                    names[family])
        self.assertEqual(names["fin"], "Superficie final corta [VIGENTE]")

    def test_h_a_count_of_one_in_the_summary_and_the_card_is_singular(self) -> None:
        """T61 (lo que vio el H3, como los avisos de la T60): las líneas del resumen y de la barra
        N de la 014 con un recuento de 1 van en singular, en los dos idiomas: la regla de orden,
        la transición (sus celdas y sus parejas), el ajuste (sus celdas y las que vuelven al
        terreno), las láminas de agua, el recinto y las bermas; con 2, en plural."""
        quarry = SimpleNamespace(
            adjusted=1, order="final_first", to_final=None,
            classes=SimpleNamespace(min_thickness_m=0.02, total=SimpleNamespace(
                levels=lambda surface: None, exp_cut_m3=0.0, exp_cut_area_ha=0.0,
                unsplit_m3=0.0, fill_m3=0.0, area_ha=lambda kind: 0.0)))
        transition = SimpleNamespace(
            settings={"surface": "des_fin_corta"},
            outcome=SimpleNamespace(
                transition=SimpleNamespace(angle_deg=35.0, volume_m3=3.0, cells=1, area_m2=4.0),
                report=SimpleNamespace(pairs=1, within_pct=100.0, threshold_m=1.0,
                                       maximum_m=0.5)))
        refit = SimpleNamespace(outcome=SimpleNamespace(refits=(
            SimpleNamespace(surface="des_fin_corta", volume_m3=2.0, cells=1, outside_cells=1),
            SimpleNamespace(surface="des_exp_corta", volume_m3=2.0, cells=2, outside_cells=1),
            SimpleNamespace(surface="des_exp_corta", volume_m3=2.0, cells=1, outside_cells=0))))
        berms = SimpleNamespace(count=1, lowest_m=125.0, highest_m=125.0)
        lines = [text for text, _alert in (
            *self.panels._quarry_lines(quarry)[:1], *self.panels._transition_lines(transition),
            *self.panels._refit_lines(refit),
            *self.panels._bench_lines(SimpleNamespace(slope_max_deg=None, slope_p99_deg=None),
                                      berms))]
        self.assertEqual(lines, [
            "Orden del diseño: Primero la superficie final · la regla de orden cambió 1 celda",
            "Transición de «des_fin_corta» a 35°: 3 m³ en 1 celda (4 m²)",
            "Salto creado en el borde: 1 pareja, el 100,00 % por debajo de 1 m; el mayor, 0,50 m",
            "«des_fin_corta» ajustada con la cara de su perfil: 2 m³ en 1 celda · 1 celda vuelve "
            "al terreno fuera del límite",
            "«des_exp_corta» ajustada con la cara de su perfil: 2 m³ en 2 celdas · 1 celda vuelve "
            "al terreno fuera del límite",
            "«des_exp_corta» ajustada con la cara de su perfil: 2 m³ en 1 celda · 0 celdas "
            "vuelven al terreno fuera del límite",
            "1 berma, cotas reales 125,0 a 125,0 m"])
        water = SimpleNamespace(outcome=SimpleNamespace(
            design=SimpleNamespace(report=SimpleNamespace(fill_m3=1.0, moved_area_m2=4.0,
                                                          slope_max_deg=None,
                                                          slope_p99_deg=None),
                                   berms=SimpleNamespace(count=0, lowest_m=None, highest_m=None)),
            cut_m3=0.0, water_cells=1), name="Balsa")
        self.assertIn("Láminas de agua como terreno de partida en 1 celda",
                      [text for text, _alert in self.panels._fill_only_lines(water)])
        boundary = SimpleNamespace(op_type=self.dprov.EXCAVATION_AREA, name="Recinto",
                                   outcome=SimpleNamespace(cells=1), notices=(),
                                   figures=(SimpleNamespace(key="des.rcn_area_m2", value=4.0),))
        self.assertEqual(self.panels.summary_lines(boundary)[0][0],
                         "Recinto excavable «Recinto»: 1 celda (4 m²)")
        self.i18n.set_language("en")
        try:
            quarry.adjusted = 2
            self.assertTrue(self.panels._quarry_lines(quarry)[0][0].endswith(
                "the order rule changed 2 cells"))
            quarry.adjusted = 1
            self.assertTrue(self.panels._quarry_lines(quarry)[0][0].endswith(
                "the order rule changed 1 cell"))
            self.assertTrue(self.panels._refit_lines(refit)[0][0].endswith(
                "in 1 cell · 1 cell back to the terrain outside the limit"))
        finally:
            self.i18n.set_language("es")

    def test_z_disable_removes_the_loaders_of_the_quarry(self) -> None:
        """Principio 8: desactivar Geoblender quita los cargadores de las rejillas de la cantera
        (y el de la 013 y el recinto, como antes)."""
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        for family in FAMILIES:
            self.assertIsNone(self.views.loader_for(f"des_{family}_corta"))
        for prefix in ("des_env_", "des_srf_", "des_brm_", "des_rcn_"):
            self.assertIsNone(self.views.loader_for(f"{prefix}corta"))


if __name__ == "__main__":
    unittest.main()

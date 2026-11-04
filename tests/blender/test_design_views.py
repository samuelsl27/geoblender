# SPDX-License-Identifier: GPL-3.0-or-later
"""Las rejillas del diseño en la vista y la barra N «Diseño» (spec 013, T27; HU-013-6; RF-013-32,
RF-013-06, RF-010-06, RF-010-08; plan 013 §5.1, D-32; comprobación manual M4).

«Cargar en la vista» de la envolvente (``des_env_``), la superficie de diseño (``des_srf_``) y la
rejilla de cotas de berma (``des_brm_``): ``bl.scene.des_views`` las carga como objetos ``DESIGN``
(``Object.geoblender.kind``), con el nombre generado de la vista («Envolvente hoyo · V01
[VIGENTE]») y en la colección de su versión; y lo que enseñan la barra N «Diseño»
(``GEOBLENDER_PT_des_design``, de la Vista 3D) y «Elemento activo» y «Cifras de la selección» de la
010 del objeto seleccionado, leído del proyecto: el estado (al día u obsoleto con su causa), los
parámetros con su insignia de tipo y su origen, las semillas y el dominio, las restricciones
aplicadas con la marca de la búsqueda de intocables pendiente y las cifras. Un proyecto por clase
(ventana de 60 × 60 m con celdas de 2 m, V01 y V02, un límite legal, un perímetro, una zona «Hoyo»,
dos sectores con la búsqueda cerrada y una ladera llana a 100 m) con una envolvente ascendente y su
escalonado en corte hechos con las órdenes reales, y las pruebas, en el orden de sus letras sobre el
mismo estado:

- RF-013-32, D-32 (a): ``DESIGN`` es un tipo de ``Object.geoblender`` con su rama «Design», las tres
  rejillas tienen su cargador (tres nombres distintos) y la barra N es un panel real de la Vista 3D.
- RF-013-32 (b): cargar las tres da un objeto ``DESIGN`` por rejilla en la colección de su dato, con
  sus vértices en las cotas de la rejilla registrada, relativos al GeoOrigin y con matriz identidad;
  la vista no escribe nada en el proyecto; cerrar los pasos a mitad no deja nada.
- RF-013-32, RF-010-06 (c): seleccionar el objeto lee su ficha del proyecto (nada se lee al dibujar) y
  la barra N enseña su estado, sus parámetros con insignia y origen, las semillas, el dominio, las
  restricciones aplicadas y las cifras registradas.
- RF-013-06, RF-013-32 (d): con la búsqueda de un sector pendiente, el resultado lleva la marca con el
  sector; un parámetro cambiado lo deja obsoleto con su causa; las dos, en la barra N. La marca sale
  además como primera fila del apartado «Cifras», en ámbar, una por sector pendiente y ninguna sin
  pendientes ni con la búsqueda hecha después (T38; F-2); nada se escribe en el proyecto.
- RF-010-06, RF-010-08 (e): «Elemento activo» y «Cifras de la selección» enseñan las mismas líneas.
- RF-013-03, principio 10 (f): sin objeto de diseño activo, la barra N enseña el resumen de la vista
  previa de las semillas; en inglés y en español.
- Principio 8 (z): desactivar Geoblender quita los cargadores y la barra N y deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import time
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw
from tests.support.trees import remove_tree

KIND = DESIGN_KIND = "DESIGN"
PANEL ="GEOBLENDER_PT_des_design"
CONTEXT_MENU = "GEOBLENDER_MT_des_context_design"
COMPUTE = "geoblender.des_compute_envelope"
LOAD = "geoblender.core_load_into_view"
VIEW_PROPERTY = "geoblender_design"
REASON = "Prueba de las rejillas del diseño en la vista"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
CLOSED_AT = "2026-11-03T10:00:00Z"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
GROUND_M = 100.0
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
PIT = (22.0, 22.0, 34.0, 34.0)
SECTORS = {"Sector 1": (2.0, 2.0, 30.0, 56.0), "Sector 2": (30.0, 2.0, 56.0, 56.0)}
MOVED_SECTOR_1 = (2.0, 2.0, 30.0, 54.0)
MOVED_SECTOR_2 = (30.0, 2.0, 54.0, 56.0)
MARK_1 = "Búsqueda de intocables pendiente en «Sector 1»."
MARK = "Búsqueda de intocables pendiente en «Sector 2»."
EXPL ="EXPL_5_60_6"
EXPL_VALUES = {"height": "5", "face": "60", "berm": "6", "anchor": "100"}
NAME = "Hoyo"
ENVELOPE, DESIGN, BERMS = "des_env_hoyo", "des_srf_hoyo", "des_brm_hoyo"
LABELS_ES = {ENVELOPE: "Envolvente", DESIGN: "Superficie de diseño", BERMS: "Cotas de berma"}
LABELS_EN = {ENVELOPE: "Envelope", DESIGN: "Design surface", BERMS: "Berm elevations"}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


class DesignViewsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, dos sectores
    con la búsqueda cerrada, una ladera llana y un perfil de banco, con una envolvente «Hoyo» y su
    escalonado hechos con las órdenes reales, para toda la clase (las pruebas, en el orden de sus
    letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d27-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.views = _module("bl.scene.views")
        cls.des_views = _module("bl.scene.des_views")
        cls.mesh = _module("bl.scene.mesh")
        cls.versions = _module("bl.scene.versions")
        cls.panels = _module("bl.ui.des_panels")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.core_props = _module("bl.props.core")
        cls.ui_provenance = _module("bl.ui.provenance")
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="diseno",
                                                      title="Diseño", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.codes = cls.declare()
        cls.declare_sectors(SECTORS)
        cls.close_search("sector_1", 1)
        cls.close_search("sector_2", 2)
        cls.ground = cls.write_grid("Ladera", np.full((int(SIZE_M / STEP_M),) * 2, GROUND_M))
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=EXPL, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
            scope="PROJECT", **EXPL_VALUES) == {"FINISHED"}
        cls.calculate()
        cls.uids = {name: cls.dataset_uid(name) for name in (ENVELOPE, DESIGN, BERMS)}

    @classmethod
    def declare(cls) -> dict[str, str]:
        """El límite legal, el perímetro de actuación y una zona «Hoyo» que se puede excavar (como
        las dejará la orden de la 012); el código de cada una por su tipo."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 3), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.AVOID, NAME, PIT)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        edited = cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                            srs_id=cls.project.record.crs_epsg)
        return {item.ctype.value: str(item.code) for item in edited.constraints}

    @classmethod
    def declare_sectors(cls, boxes: dict[str, tuple[float, float, float, float]]) -> None:
        """Los sectores de búsqueda (``core_sector``), como los dejará «Declarar de nuevo desde una
        capa…»: cada declaración sustituye a la anterior."""
        sectors = tuple(
            cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name, (ring(box),))
            for index, (name, box) in enumerate(boxes.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.replace_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str, minutes: int) -> None:
        """Cierra la búsqueda de intocables de un sector (con su huella), como hará la orden de la
        012: queda sin la marca de pendiente."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(f"search{minutes}{'0' * 25}", handle.uid, code,
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON, CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto de la ventana con ``values`` (como la deja «Rejilla del
        proyecto desde un MDT», ``gis.resample``); el nombre de su dato."""
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

    @classmethod
    def calculate(cls) -> None:
        """Una envolvente ascendente de 45° desde los 90 m de la zona «Hoyo» con su escalonado en
        corte, con las órdenes reales y de una vez (como desde un guion): calcular, crear la
        envolvente y crear el escalonado."""
        form = {"name": NAME, "seeds_from": "FIXED", "zone": f"constraint:{cls.codes['avoid']}",
                "elevation": "90", "direction": "UP", "metric": "CHAMFER5",
                "slope_mode": "CONSTANT", "slope": "45", "stepped": True, "base_profile": EXPL,
                "sense": "CUT", "start": cls.ground}
        compute = bpy.ops.geoblender.des_compute_envelope
        assert compute("EXEC_DEFAULT", **form) == {"FINISHED"}
        assert compute("EXEC_DEFAULT", confirm=True) == {"FINISHED"}  # la envolvente; sigue el resto
        assert compute("EXEC_DEFAULT", confirm=True) == {"FINISHED"}  # el escalonado
        cls.project.refresh_header()

    @classmethod
    def dataset_uid(cls, name: str) -> str:
        with cls.project.read() as conn:
            return str(conn.execute("SELECT uid FROM gb_dataset WHERE name = ? AND status = "
                                    "'current'", (name,)).fetchone()[0])

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def origin(self) -> Any:
        return self.project.origin

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que ver no cambia)."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def loaded(self) -> dict[str, Any]:
        """Los objetos ``DESIGN`` de la escena por el uid de su dato."""
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects
                if obj.geoblender.kind == KIND}

    def load(self, *names: str) -> None:
        """«Cargar en la vista» de las rejillas ``names`` por el uid de su dato (como lo pide el
        inventario: el nombre de un dato de versión no basta si hubiera dos versiones con él)."""
        for name in names:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=self.uids[name]),
                             {"FINISHED"})

    def choose(self, name: str) -> Any:
        """Selecciona y activa el objeto de la rejilla ``name`` y lee su ficha como lo hace Blender
        al cambiar el objeto activo."""
        obj = self.loaded()[self.uids[name]]
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        return obj

    def deselect(self) -> None:
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()

    def panel_texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    def lines(self) -> list[tuple[str, str, bool]]:
        """Las líneas de la barra N ya leídas: (cómo se dibuja, texto, si va en alerta)."""
        return [(row.kind, row.name, bool(row.alert)) for row in self.view.item]

    def texts(self) -> list[str]:
        return [text for _kind, text, _alert in self.lines()]

    def split(self) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]]:
        """Las líneas de la barra N ya leídas, partidas en lo que va antes del apartado «Cifras» (la
        ficha) y ese apartado (su encabezado y lo que sigue hasta el final)."""
        rows = self.lines()
        start = next(index for index, (kind, text, _alert) in enumerate(rows)
                     if kind == "heading" and text == "Cifras")
        return rows[:start], rows[start:]

    def alert_texts(self) -> str:
        """Lo que la barra N dibuja en alerta (en ámbar), con las etiquetas partidas al ancho de la
        barra vueltas a unir con un espacio."""
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        return " ".join(item.text for item in layout.of_kind("label") if item.alert)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_kind_the_loaders_and_the_side_panel(self) -> None:
        """RF-013-32, D-32: ``DESIGN`` es un tipo de ``Object.geoblender`` con su rama «Design»; las
        tres rejillas (``des_env_``, ``des_srf_``, ``des_brm_``) tienen su cargador, del mismo tipo y
        con un nombre cada una; la barra N «Diseño» es un panel real de la Vista 3D y el menú
        contextual «Diseño ▾» de la entrada «013» sigue disponible."""
        self.assertIn(KIND, [item[0] for item in self.core_props.OBJECT_KINDS])
        self.assertEqual(self.views.BRANCHES[KIND], (("design", "Design"),))
        labels = {}
        for prefix, label in (("des_env_", "Envelope"), ("des_srf_", "Design surface"),
                              ("des_brm_", "Berm elevations")):
            loader = self.views.loader_for(f"{prefix}hoyo")
            self.assertEqual((loader.prefix, loader.kind, loader.label), (prefix, KIND, label))
            labels[prefix] = loader.label
        self.assertEqual(len(set(labels.values())), 3)  # tres nombres: dos objetos no chocan
        for name in ("des_bmt_hoyo", "des_rpt_hoyo"):  # las tablas no se cargan en la vista
            self.assertIsNone(self.views.loader_for(name))
        cat = self.commands.catalog()
        self.assertEqual(cat.contexts[KIND].id, CONTEXT_MENU)
        self.assertTrue(self.commands.is_available(CONTEXT_MENU))
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_category,
                          panel.bl_label), ("VIEW_3D", "UI", "Diseño", "Diseño"))
        self.assertIn(panel, self.panels.classes)
        self.assertFalse(panel.poll(bpy.context))  # sin objeto de diseño ni vista previa

    def test_b_load_one_design_object_per_grid_on_the_registered_elevations(self) -> None:
        """RF-013-32, D-32, ADR-0005 (M4): «Cargar en la vista» de las tres rejillas da un objeto
        ``DESIGN`` por rejilla, con el nombre de la vista («Envolvente hoyo · V01 [VIGENTE]»), en la
        colección de su dato (bajo la de su versión), con matriz identidad y sus vértices, vueltos a
        absolutos, en el centro de una celda y a la cota de la rejilla registrada; la vista no
        escribe nada en el proyecto y cerrar los pasos a mitad no deja nada."""
        files, operations = self.files(), self.operations()
        meshes = len(bpy.data.meshes)
        steps = self.views.load_steps(bpy.context, self.project, [self.uids[ENVELOPE]])
        for _ in range(50):  # hasta que la malla está creada, antes del último paso
            step = next(steps)
            if len(bpy.data.meshes) > meshes:
                break
            self.assertIsNone(step.result, "se cargó sin pasar por la malla")
        self.assertGreater(len(bpy.data.meshes), meshes)
        steps.close()
        self.assertEqual(len(bpy.data.meshes), meshes)
        self.assertEqual(self.loaded(), {})

        self.load(ENVELOPE, DESIGN, BERMS)
        self.assertEqual((self.files(), self.operations()), (files, operations))
        loaded = self.loaded()
        self.assertEqual(set(loaded), set(self.uids.values()))
        for name, uid in self.uids.items():
            with self.subTest(dato=name):
                obj = loaded[uid]
                self.assertEqual(obj.name, f"{LABELS_ES[name]} hoyo · V01 [VIGENTE]")
                self.assertEqual(obj.geoblender.project_uid, self.project.uid)
                self.assertEqual(obj.users_collection[0].get("geoblender_key"), f"dataset:{uid}")
                path = self.views.collection_path(obj.users_collection[0])
                self.assertTrue(path[-1].startswith(LABELS_ES[name]), path)
                self.assertTrue(path[-2].startswith("V01"), path)
                self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))  # nunca el origen en location
                self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
                raster = self.surfaces.read_surface(self.project, name, version_uid=self.v01.uid)
                world = self.mesh.mesh_vertices_world(obj.data, self.origin)
                self.assertGreater(len(world), 8)
                self.assertTrue(np.isfinite(world).all())
                grid = raster.grid
                columns = (world[:, 0] - grid.west) / grid.dx - 0.5
                rows = (grid.north - world[:, 1]) / grid.dy - 0.5
                np.testing.assert_allclose(columns, np.rint(columns), atol=1e-6)  # centros de celda
                np.testing.assert_allclose(rows, np.rint(rows), atol=1e-6)
                found = raster.values[np.rint(rows).astype(int), np.rint(columns).astype(int)]
                np.testing.assert_allclose(world[:, 2], found, atol=1e-4)
                self.assertGreater(len(obj.geoblender.figures), 0)
        # Cargar de nuevo lo sustituye: no se duplica.
        self.load(DESIGN)
        self.assertEqual(len(self.loaded()), 3)
        # La vista no transforma coordenadas: una rejilla en otro CRS se rechaza y no se carga.
        georef = _module("core.georef")
        raster = self.surfaces.read_surface(self.project, ENVELOPE, version_uid=self.v01.uid)
        other = _module("gis.raster").Raster(
            raster.grid, raster.values, georef.load_catalog().horizontal(25831), raster.vertical)
        with mock.patch.object(self.surfaces, "read_surface", return_value=other):
            outcome = self.views.load_datasets(bpy.context, self.project, [self.uids[ENVELOPE]])
        self.assertEqual((outcome.loaded, len(outcome.errors)), ((), 1))
        self.assertIn("está en EPSG:25831 + EPSG:5782 y el proyecto en EPSG:25830 + EPSG:5782",
                      outcome.errors[0])
        self.assertEqual(set(self.loaded()), set(self.uids.values()))  # lo cargado sigue

    def test_c_the_side_panel_shows_state_parameters_seeds_constraints_and_figures(self) -> None:
        """RF-013-32, RF-010-06 (M4): seleccionar la envolvente lee su ficha del proyecto (al cambiar
        el objeto activo, no al dibujar) y la barra N enseña su título, su estado «al día», sus ajustes,
        sus parámetros con su insignia de tipo, las semillas y el dominio de trabajo, las
        restricciones aplicadas y las cifras registradas con su insignia; la del escalonado, los
        parámetros de su perfil con su tipo, origen y decisor y su envolvente."""
        panel = getattr(bpy.types, PANEL)
        files, operations = self.files(), self.operations()
        self.choose(ENVELOPE)
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((self.view.item_uid, self.view.item_project, self.view.item_found),
                         (self.uids[ENVELOPE], self.project.uid, True))
        with mock.patch.object(self.project, "read", side_effect=AssertionError("se lee al dibujar")):
            shown = self.panel_texts()  # nada se lee al dibujar
        joined = "\n".join(shown)
        self.assertEqual(self.view.item_title, "Envolvente · Hoyo")
        self.assertIn("Envolvente · Hoyo", shown)
        kinds = {text: kind for kind, text, _alert in self.lines()}
        self.assertIn("Al día", self.texts())
        self.assertFalse(any(alert for _k, _t, alert in self.lines()))
        # Los ajustes de la orden, los de su procedencia (dirección, métrica, pendiente…).
        self.assertTrue(any(text.startswith("Ajustes:") and "Envolvente ascendente" in text
                            for text in self.texts()), self.texts())
        # Los parámetros que leyó, con su insignia de tipo (la envolvente constante lee el espesor).
        self.assertEqual(kinds["Parámetros"], "heading")
        self.assertTrue(any("Espesor mínimo" in text and "[" in text and "]" in text
                            for text in self.texts()), self.texts())
        # Las semillas y el dominio.
        self.assertEqual(kinds["Semillas y dominios"], "heading")
        self.assertIn("Semillas: cota fija 90 m · zona de «Hoyo»", self.texts())
        self.assertIn("Dominio de trabajo: todo el de las máscaras", self.texts())
        # Las restricciones aplicadas (activas en su versión).
        self.assertEqual(kinds["Restricciones aplicadas"], "heading")
        for wanted in ("Límite legal · Concesión", "Perímetro de actuación · Perímetro",
                       "Preferible no afectar · Hoyo"):
            self.assertIn(wanted, self.texts())
        # Las cifras registradas, con su insignia: las mismas del proyecto.
        figures_mod = _module("core.provenance.figures")
        stored = [figures_mod.FigureRecord.from_row(row) for row in self.rows(
            f"SELECT {figures_mod.RECORD_COLUMNS} FROM gb_figure AS f WHERE operation_uid = "
            "(SELECT operation_uid FROM gb_dataset WHERE uid = ?) ORDER BY fid",
            self.uids[ENVELOPE])]
        self.assertEqual({figure.key for figure in stored}, {
            "des.env_cells", "des.env_area_m2", "des.env_min_m", "des.env_max_m"})
        for figure in stored:
            self.assertIn(f"[CAL] {figure.text(language='es')}", self.texts())
        self.assertEqual(kinds["Cifras"], "heading")
        self.assertIn("Cifras", joined)
        # El escalonado: sus parámetros (el perfil), con tipo, origen y decisor.
        self.choose(DESIGN)
        self.assertEqual(self.view.item_title, "Superficie de diseño · Hoyo")
        texts = self.texts()
        height = [text for text in texts if text.startswith("Altura de banco")]
        self.assertTrue(height, texts)
        for part in ("5 m", "[ADO]", SOURCE, PERSON, "proyecto"):
            self.assertIn(part, height[0])
        self.assertIn("Perfiles asignados: base EXPL_5_60_6", texts)  # el perfil base (RF-013-21)
        self.assertIn("Envolvente: «Hoyo»", texts)
        self.assertIn("Semillas: cota fija 90 m · zona de «Hoyo»", texts)  # las de su envolvente
        self.assertEqual(
            self.panels.profiles_text(
                {"base_profile": "expl", "sector_profiles": {"sector_2": "rest", "": "expl"}},
                {"expl": EXPL, "rest": "REST_5_35_3"},
                {"sector_2": "Sector 2", "": "el perímetro de actuación"}),
            f"base {EXPL} · Sector 2: REST_5_35_3 · el perímetro de actuación: {EXPL}")
        self.assertEqual(self.panels.profiles_text({"base_profile": "", "sector_profiles": {}},
                                                   {}, {}), "")
        self.choose(BERMS)
        self.assertEqual(self.view.item_title, "Cotas de berma · Hoyo")
        self.assertIn("Cifras", self.texts())
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_d_a_pending_search_marks_the_result_and_a_changed_parameter_makes_it_stale(self) -> None:
        """RF-013-06, RF-013-32 (M4, M6): si el sector 2 pierde su búsqueda de intocables (se declara
        con otro contorno), la barra N de un resultado cuyo dominio lo tocó lleva, en alerta, la marca
        «Búsqueda de intocables pendiente en «Sector 2»» y, si cambia el espesor mínimo que leyó, el
        resultado queda «Obsoleto» con su causa; el sector 1, con su búsqueda vigente, no se marca.
        Antes de perderla, el apartado «Cifras» no lleva marca (F-2, T38); con ella, la lleva como su
        primera fila, en ámbar, y las cifras siguen iguales."""
        self.choose(DESIGN)
        self.assertFalse([text for text in self.texts() if "pendiente" in text])
        self.assertNotIn(MARK, self.alert_texts())
        _card, plain = self.split()  # sin marcas, el apartado «Cifras» es el de siempre
        self.assertEqual(plain[0], ("heading", "Cifras", False))
        self.assertGreater(len(plain), 1)
        self.assertEqual({kind for kind, _text, _alert in plain[1:]}, {"figure"})
        self.declare_sectors({"Sector 1": SECTORS["Sector 1"], "Sector 2": MOVED_SECTOR_2})
        store = _module("core.params").ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, "res.verify.min_thickness_m", value=0.5, kind="ADOPTADO",
                         source="Criterio de la prueba", source_kind="person", decided_by=PERSON,
                         reason=REASON)
        self.project.refresh_header()
        self.assertTrue(self.ui_provenance.refresh(force=True))  # la escucha lee la ficha otra vez
        lines, figures = self.split()
        marks = [(text, alert) for _kind, text, alert in lines if "pendiente" in text]
        self.assertEqual(marks, [(MARK, True)])  # en la ficha, donde ya salía
        # Y junto a las cifras (F-2): la primera fila de su apartado, en ámbar, y las cifras, como antes.
        self.assertEqual(figures[:2], [("heading", "Cifras", False), ("field", MARK, True)])
        self.assertEqual(figures[2:], plain[1:])
        self.assertEqual(self.alert_texts().count(MARK), 2)  # las dos se dibujan en alerta
        stale =[(text, alert) for _kind, text, alert in lines if text.startswith("Obsoleto")]
        self.assertEqual(len(stale), 1, lines)
        self.assertTrue(stale[0][1])
        self.assertNotIn("Al día", self.texts())
        self.assertIn(stale[0][0], " ".join(self.panel_texts()))  # partida al ancho de la barra N
        self.assertIn("cambió Espesor mínimo", stale[0][0])  # la causa, la que dice la procedencia
        # El parámetro cambiado sale en alerta con su valor de hoy; los demás, no.
        changed = [(text, alert) for _kind, text, alert in lines
                   if text.startswith("Espesor mínimo")]
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0][1])
        self.assertTrue(changed[0][0].endswith("hoy: 0,5 m [ADO]"), changed[0][0])
        self.assertFalse([alert for _kind, text, alert in lines if text.startswith("Altura de banco")
                          and alert])
        # También en la envolvente, que lee los mismos sectores.
        self.choose(ENVELOPE)
        self.assertIn(MARK, self.texts())
        # Una restricción desactivada en la versión deja de estar entre las aplicadas.
        self.assertIn("Preferible no afectar · Hoyo", self.texts())
        with self.project.write_transaction() as conn:
            store.change(conn, _module("core.constraints.params").active_key(self.codes["avoid"]),
                         value=False, kind="ADOPTADO", source="Criterio de la prueba",
                         source_kind="person", decided_by=PERSON, reason=REASON,
                         version=self.v01.uid)
        self.project.refresh_header()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertNotIn("Preferible no afectar · Hoyo", self.texts())
        self.assertIn("Límite legal · Concesión", self.texts())

    def test_d_b_the_pending_mark_is_the_first_row_of_the_figures_one_per_pending_sector(self) -> None:
        """RF-013-06 (F-2, T38): la marca de la búsqueda pendiente sale también como las primeras
        filas del apartado «Cifras» de la barra N, tras su encabezado, una por sector pendiente (en
        el orden de los sectores), en ámbar y sin el uid de ninguna cifra (no es una cifra: el clic y
        la selección de las cifras no la ven), y sigue donde ya salía (la ficha); con la búsqueda
        hecha después desaparece de las dos; las cifras registradas, el orden y los textos son los
        mismos con y sin marca; ver no escribe nada en el proyecto (la marca es del estado de ahora,
        no del cálculo: el informe y las cifras guardados no la llevan)."""
        self.choose(DESIGN)
        _card, one = self.split()  # tras la prueba anterior, solo el sector 2 está pendiente
        self.assertEqual([text for _kind, text, _alert in one if "intocables pendiente" in text],
                         [MARK])
        figures = one[2:]
        self.assertGreater(len(figures), 0)
        self.assertEqual({kind for kind, _text, _alert in figures}, {"figure"})
        stored = self.rows("SELECT count(*) FROM gb_figure AS f WHERE operation_uid = "
                           "(SELECT operation_uid FROM gb_dataset WHERE uid = ?)", self.uids[DESIGN])
        self.assertEqual(len(figures), int(stored[0][0]))  # ninguna cifra más ni menos

        # Los dos sectores pendientes: una fila cada uno, en el orden de los sectores.
        self.declare_sectors({"Sector 1": MOVED_SECTOR_1, "Sector 2": MOVED_SECTOR_2})
        self.project.refresh_header()
        files, operations = self.files(), self.operations()  # desde aquí, solo se lee
        self.assertTrue(self.panels.read_selected(bpy.context))
        lines, both = self.split()
        self.assertEqual(both[:3], [("heading", "Cifras", False), ("field", MARK_1, True),
                                    ("field", MARK, True)])
        self.assertEqual(both[3:], figures)
        self.assertEqual([text for _kind, text, _alert in lines if "intocables pendiente" in text],
                         [MARK_1, MARK])  # la ficha las conserva, una vez cada una
        self.assertEqual({row.uid for row in self.view.item if row.kind != "figure"}, {""})
        self.assertNotIn("", {row.uid for row in self.view.item if row.kind == "figure"})
        drawn = self.alert_texts()
        self.assertEqual((drawn.count(MARK_1), drawn.count(MARK)), (2, 2))  # ficha y cifras
        self.choose(ENVELOPE)  # también la envolvente, que lee los mismos sectores
        self.assertEqual([text for _kind, text, _alert in self.split()[1]
                          if "intocables pendiente" in text], [MARK_1, MARK])
        self.assertEqual((self.files(), self.operations()), (files, operations))

        # Con la búsqueda hecha después, desaparecen: el apartado vuelve a ser el de siempre.
        self.close_search("sector_1", 3)
        self.close_search("sector_2", 4)
        self.project.refresh_header()
        files, operations = self.files(), self.operations()
        for name in (ENVELOPE, DESIGN):
            with self.subTest(search_done=name):
                self.choose(name)
                _card, block = self.split()
                self.assertFalse([text for text in self.texts() if "intocables pendiente" in text])
                self.assertEqual(block[0], ("heading", "Cifras", False))
                self.assertEqual({kind for kind, _text, _alert in block[1:]}, {"figure"})
                self.assertNotIn("Búsqueda de intocables", self.alert_texts())
        self.assertEqual(block[1:], figures)  # el de la superficie de diseño: las mismas cifras
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_e_the_active_item_and_the_selection_figures_show_the_same_lines(self) -> None:
        """RF-010-06, RF-010-08, RF-013-32: «Elemento activo» enseña, tras su ficha, las líneas de la
        barra N (sin las cifras, que ya son las de su ficha) y «Cifras de la selección», las mismas;
        un objeto del usuario no las tiene."""
        self.choose(DESIGN)
        wanted = [text for kind, text, _alert in self.lines() if kind != "figure"]
        wanted = wanted[:wanted.index("Cifras")] if "Cifras" in wanted else wanted
        manager = bpy.context.window_manager
        self.assertTrue(self.view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(manager, self.view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(wanted):], wanted)
        self.assertEqual(self.view_panels.fill_selection_figures(bpy.context), 1)  # un dato
        selection = [row.text for row in getattr(
            manager, self.view_panels.WINDOW_MANAGER_PROPERTY).selection]
        self.assertTrue(set(wanted) <= set(selection))
        # Ni un objeto del usuario ni uno de diseño de otro proyecto tienen ficha de este.
        user = bpy.data.objects.new("Mío", None)
        foreign = bpy.data.objects.new("De otro proyecto", None)
        foreign.geoblender.kind = KIND
        foreign.geoblender.dataset_uid = self.uids[DESIGN]
        foreign.geoblender.project_uid = "otro-proyecto"
        for obj in (user, foreign):
            bpy.context.scene.collection.objects.link(obj)
            self.addCleanup(bpy.data.objects.remove, obj)
            bpy.context.view_layer.objects.active = obj
            self.view_panels.on_active_changed()
            self.assertEqual(self.view.item_uid, "", obj.name)
            self.assertFalse(getattr(bpy.types, PANEL).poll(bpy.context), obj.name)

    def test_f_the_preview_summary_the_languages_and_each_read_is_short(self) -> None:
        """RF-013-03, principio 10, RNF-013-07: sin objeto de diseño activo, la barra N enseña el
        resumen de la vista previa de las semillas (los avisos en alerta) mientras lo hay; en inglés
        todo sale en inglés (la pestaña, el título, los apartados y las líneas); cada lectura del
        proyecto para la barra N tarda menos de 0,2 s de CPU."""
        panel = getattr(bpy.types, PANEL)
        self.deselect()
        self.assertFalse(panel.poll(bpy.context))
        self.panels.show_preview([("Semillas: 12 celdas (48 m²)", False), ("Aviso de prueba", True)])
        self.addCleanup(self.panels.show_preview, [])
        self.assertTrue(panel.poll(bpy.context))
        layout = draw(panel, bpy.context)
        self.assertIn("Vista previa de las semillas", layout.texts())
        self.assertIn("Semillas: 12 celdas (48 m²)", layout.texts())
        self.assertIn("Aviso de prueba", layout.texts())
        self.panels.show_preview([])
        self.assertFalse(panel.poll(bpy.context))

        self.choose(DESIGN)
        started = time.process_time()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertLess(time.process_time() - started, 0.2)
        spanish = self.panel_texts()
        self.ui_i18n.apply("en")
        self.addCleanup(self.ui_i18n.apply, "es")
        self.assertEqual((panel.bl_category, panel.bl_label), ("Design", "Design"))
        self.assertTrue(self.panels.read_selected(bpy.context))
        english = self.panel_texts()
        self.assertEqual(self.view.item_title, "Design surface · Hoyo")
        for wanted in ("Parameters", "Seeds and domains", "Applied constraints", "Figures",
                       "Profiles: base EXPL_5_60_6",
                       "Seeds: fixed elevation 90 m · zone of «Hoyo»",
                       "Work domain: the whole domain of the masks",
                       "Legal limit · Concesión"):
            self.assertIn(wanted, self.texts() + english)
        self.assertNotEqual(english, spanish)

    def test_z_disable_leaves_nothing_of_the_design_views(self) -> None:
        """Principio 8: con un objeto de diseño seleccionado, desactivar Geoblender quita los tres
        cargadores, el panel de la barra N y su lectura, y la huella de Blender vuelve a la del
        principio de la sesión."""
        self.choose(DESIGN)
        self.assertEqual(self.view.item_uid, self.uids[DESIGN])
        self.assertIn(self.panels.on_project_changed, self.ps.listeners())
        self.assertIn(DESIGN_KIND, self.view_panels._OBJECT_LINES)  # noqa: SLF001
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertIsNone(getattr(bpy.types, PANEL, None))
        self.assertNotIn(self.panels.on_project_changed, self.ps.listeners())
        self.assertNotIn(DESIGN_KIND, self.view_panels._OBJECT_LINES)  # noqa: SLF001
        with mock.patch.object(self.panels, "read_selected_safely") as read:
            self.view_panels.on_project_read(self.project)  # la ficha se lee: nadie más se entera
        read.assert_not_called()
        for prefix in ("des_env_", "des_srf_", "des_brm_"):
            self.assertIsNone(self.views.loader_for(f"{prefix}hoyo"))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()

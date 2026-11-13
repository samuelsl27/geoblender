# SPDX-License-Identifier: GPL-3.0-or-later
"""«Solo relleno…» en Blender (spec 014, T30; HU-014-6; RF-014-22 a RF-014-25, RF-014-29; plan 014
§5.3.3, §5.5; comprobación manual M5).

:class:`GEOBLENDER_OT_des_design_fill_only` (``geoblender.des_design_fill_only``, en Diseño ▸
Cantera) calcula con ``design.steps.fill_only_run`` la operación ``des.fill_only`` de la versión
activa: el escalonado **en relleno** de la 013 de una envolvente de la versión sobre la superficie
de partida, que nunca corta, con el pie dentro del relleno admitido de la 012 y las láminas de agua
de una capa como terreno de partida. Su diálogo es el del escalonado en relleno de la 013 (el
nombre, la envolvente, la superficie de partida, el ancla, el perfil base y el de cada sector) más
la capa de láminas y su campo; propone «Solo relleno», la primera envolvente de la versión, el
terreno y el campo «cota». Calcular, Crear, Cancelar y Esc son los de las demás órdenes de la 014
(``_CalculateAndCreate``): nada se registra hasta Crear. Su superficie es una ``des_srf_``, que
carga el cargador de la 013, y la barra N enseña su ficha con la capa de láminas.

Un proyecto pequeño por clase (ventana de 40 × 40 m con celdas de 2 m, V01, el límite legal de
(4, 4) a (36, 36) con 2 m hacia dentro, el perímetro de (2, 2) a (38, 38), la torre intocable de
(16, 26) a (20, 30), junto a la lámina, un sector con la búsqueda cerrada, la ladera
``100 + 0,25·y + 0,0625·x``, el perfil ``REST_5_35_6`` y la capa de láminas ``gis_fea_laminas``
con una lámina de (8, 24) a (16, 32) a 108 m) con la envolvente «Plataforma» de V01: descendente,
de 30°, desde 110 m en las celdas de la lámina (datos de la prueba). Las pruebas, en el orden de
sus letras sobre el mismo estado.

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

FILL_ONLY = "geoblender.des_design_fill_only"
FILL_ONLY_CLASS = "GEOBLENDER_OT_des_design_fill_only"
FILL_ONLY_TYPE = "des.fill_only"
DESIGN_MENU = "GEOBLENDER_MT_ui_design"
KIND = "DESIGN"
REASON = "Prueba de «Solo relleno…»"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de restauración"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 40.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (4.0, 4.0, 36.0, 36.0)
PERIMETER = (2.0, 2.0, 38.0, 38.0)
TOWER = (16.0, 26.0, 20.0, 30.0)
SECTOR = ("Sector único", (0.0, 0.0, 40.0, 40.0))
CLOSED_AT = "2026-11-13T10:00:00Z"
REST, REST_CODE = "REST_5_35_6", "rest_5_35_6"
LAYERS_TYPE = "gis.test_fill_only_layers"
WATER_LAYER = "gis_fea_laminas"
WATER_BOX = (8.0, 24.0, 16.0, 32.0)
WATER_M = 108.0
RAISED_CELLS = 10
"""Las celdas de la lámina con la ladera por debajo de 108 m, a mano: ``0,25·y + 0,0625·x < 8`` en
los centros de ``x`` = 9 a 15 e ``y`` = 25 a 31 da las cuatro columnas de ``y`` = 25 y 27 y dos de
``y`` = 29."""
ENVELOPE = "Plataforma"
ENVELOPE_M, ENVELOPE_DEG = 110.0, 30.0
NAME = "Balsa"
PROPERTIES = {
    "name": ("Name", "Name of the fill-only design, unique in the active version"),
    "envelope": ("Envelope", "Envelope of the active version that is benched in fill: the design "
                             "only fills"),
    "start": ("Start surface", "Surface the benching starts from: the ground the design is "
                               "composed with"),
    "anchor": ("Anchor", "Elevation the benches are anchored to: that of each profile or a grid "
                         "of anchors of the project or of the active version"),
    "base_profile": ("Base profile", "Bench profile of the cells without a sector (and of the "
                                     "sectors without their own)"),
    "water_layer": ("Water sheets", "Layer of polygons with the elevation of each water sheet "
                                    "(none: no water sheets)"),
    "water_field": ("Water elevation field", "Numeric field of the layer of water sheets with the "
                                             "elevation of each sheet in metres"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def centers() -> tuple[np.ndarray, np.ndarray]:
    """Los centros de celda locales ``(x, y)`` de la ventana (fila 0 al norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    return np.meshgrid(STEP_M * index + STEP_M / 2, SIZE_M - (STEP_M * index + STEP_M / 2))


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (fila 0 al norte)."""
    x, y = centers()
    return 100.0 + 0.25 * y + 0.0625 * x


def inside(box: tuple[float, float, float, float]) -> np.ndarray:
    """Las celdas con el centro dentro del rectángulo local ``box``."""
    x, y = centers()
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class DesignFillOnlyTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la balsa, para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t30-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.views = _module("bl.scene.views")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.dmodel = _module("design.model")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = _module("core.versions.store").create_version(
                conn, cls.project, feature="balsa", title="Balsa", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.write_layer(WATER_LAYER, ((ring(WATER_BOX),),), {"cota": WATER_M})
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=REST, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
            scope="PROJECT", height="5", face="35", berm="6", anchor="125") == {"FINISHED"}
        dmodel = cls.dmodel
        envelope = dmodel.EnvelopeRequest(
            ENVELOPE, "down", dmodel.SeedSource("fixed", zone=dmodel.Zone("layer", WATER_LAYER),
                                                elevation_m=ENVELOPE_M), slope_deg=ENVELOPE_DEG)
        found = None
        for found in _module("design.steps").envelope_run(cls.project, envelope,
                                                          version=cls.v01.uid):
            pass
        found.result.create()
        cls.dataset = cls.dprov.dataset_name("srf", NAME)
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación, la torre intocable (sin
        resguardo) y el sector de búsqueda, con su búsqueda cerrada, como los dejan las órdenes de
        la 012."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 13), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                                                 row(types.ACTION_PERIMETER, "Perímetro",
                                                     PERIMETER),
                                                 row(types.UNTOUCHABLE, "Torre", TOWER)],
                                   params=declaration, srs_id=cls.project.record.crs_epsg)
        operations = _module("core.provenance.operations")
        sector = cls.cmodel.Sector(f"sector1{'0' * 26}", "sector_1", SECTOR[0], (ring(SECTOR[1]),))
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, (sector,), srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sector de prueba")
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, "sector_1",
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

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

    @classmethod
    def write_layer(cls, name: str, entity: tuple[tuple[np.ndarray, ...], ...],
                    numbers: dict[str, float]) -> None:
        """Una capa de polígonos ``gis_fea_…`` de UNA entidad con el campo ``nombre`` y los campos
        numéricos ``numbers`` (``DOUBLE``), como la deja la importación de la 006."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
                   *(vector.FieldColumn(field, field, "DOUBLE") for field in numbers))
        values = {"nombre": ("Balsa 1",), **{field: (value,) for field, value in numbers.items()}}
        layer = vector.FeatureLayer("polygon", (1,), (entity,), columns, values)
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
                immutable=False),), message="Capa de prueba de la balsa")

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no sigue

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(FILL_ONLY)

    @property
    def view(self) -> Any:
        return bpy.context.window_manager.geoblender_design

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def names(self) -> list[str]:
        """Los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(item.relative_to(root)) for item in root.rglob("*")
                      if item.is_file() and item.suffix != ".gpkg-journal")

    def state(self) -> tuple[Any, ...]:
        """Lo que la orden podría dejar: operaciones, datos, cifras y ficheros."""
        return (self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
                self.rows("SELECT name, status FROM gb_dataset ORDER BY name"),
                self.rows("SELECT count(*) FROM gb_figure"), self.names())

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: «Balsa», el relleno de la plataforma con la lámina."""
        return {"name": NAME, "envelope": ENVELOPE, "start": self.ground, "base_profile": REST,
                "water_layer": WATER_LAYER, "water_field": "cota", "in_steps": False, **values}

    def fake_dialog(self, selected: tuple[Any, ...] = (), **values: Any
                    ) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana), con los
        objetos ``selected`` seleccionados en la vista."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=selected,
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "envelope": "", "start": "", "base_profile": "", "anchor": "none",
            "water_layer": "none", "water_field": "", "confirm": False, "in_steps": False,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, report=lambda kind, text: None, **fields), context, dialog

    def loaded(self, name: str) -> Any:
        """El objeto de la vista del dato vivo ``name`` (lo carga si no está)."""
        (uid,) = [row[0] for row in self.rows(
            "SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", name)]
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        if not found:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
            found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        self.assertEqual(len(found), 1)
        return found[0]

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{FILL_ONLY} no está en marcha")
        return found[0]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-014-22, RF-014-24, RF-014-29 (plan §5.3.3, §5.5): «Solo relleno…» es una orden real
        de ``des.fill_only`` en Diseño, con la puerta de la procedencia y los pasos con Esc; sus
        propiedades tienen nombre y descripción en español; su lista de envolventes tiene las de
        la versión; su diálogo propone «Solo relleno», la primera envolvente, el terreno y el
        campo «cota»; lo dado no cambia; dibuja lo del escalonado en relleno de la 013 y las
        láminas con su campo."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (FILL_ONLY_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        command = self.commands.catalog().commands[FILL_ONLY]
        self.assertEqual((command.label_es, command.home), ("Solo relleno…", DESIGN_MENU))
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[FILL_ONLY_TYPE].commands,
                         (FILL_ONLY,))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        listed = [item[0] for item in self.panels.envelope_items(None, None)]
        self.assertEqual(listed, [ENVELOPE])

        fake, context, dialog = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Solo relleno…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.envelope, fake.start, fake.water_field),
                         ("Solo relleno", ENVELOPE, self.ground, "cota"))
        given, context, _dialog = self.fake_dialog(
            name="Mía", water_field="nivel",
            properties=SimpleNamespace(is_property_set=lambda name: name == "water_field"))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.water_field), ("Mía", "nivel"))
        shown = draw(cls, bpy.context, name=NAME, envelope=ENVELOPE, start=self.ground,
                     anchor="none", base_profile=REST, water_layer=WATER_LAYER,
                     water_field="cota", confirm=False).texts()
        for heading in ("Nombre", "Envolvente", "Superficie de partida", "Ancla", "Perfil base",
                        "Láminas de agua", "Campo de cota"):
            self.assertIn(heading, shown)

    def test_b_calculate_then_create_the_fill_only_design(self) -> None:
        """RF-014-22 a RF-014-25, RF-014-29 (M5): Calcular desde un guion deja el cálculo abierto
        con su resumen (en los dos idiomas) y solo el temporal; la superficie no corta, mueve 0 m³
        en la torre aunque la plataforma la alcanza, no rellena fuera del relleno admitido (ni
        fuera del límite) y la lámina es su partida en sus 10 celdas por debajo de 108 m; Crear
        registra ``des.fill_only`` hecha en V01 con ``des_srf_`` y ``des_rpt_`` y sus cifras: las
        del escalonado y ``des.fill_only_cut_m3`` = 0 m³."""
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_design_fill_only(
            "EXEC_DEFAULT", **self.form()), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        self.assertEqual((held.op_type, held.name, held.version), (FILL_ONLY_TYPE, NAME, "V01"))
        after = self.state()
        self.assertEqual(after[:3], before[:3], "calcular no registra nada")
        (temporary,) = sorted(set(after[3]) - set(before[3]))
        self.assertIn(".tmp", temporary)
        self.assertEqual(self.view.summary_title, f"Diseño «solo relleno» «{NAME}» en V01")
        summary = [line.name for line in self.view.summary]
        self.assertTrue(summary[0].startswith(f"Diseño «solo relleno» «{NAME}»: terraplén "),
                        summary)
        self.assertIn("corte 0,00 m³", summary[0])
        self.assertIn(f"Láminas de agua como terreno de partida en {RAISED_CELLS} celdas",
                      summary)
        self.assertNotIn("Sin bermas: no se mueve nada", summary)  # rellena: sí se mueve
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        english = [line.name for line in self.view.summary]
        self.assertTrue(english[0].startswith(f"Fill-only design «{NAME}»: fill "), english)
        self.i18n.set_language("es")
        outcome = held.outcome
        surface, start, terrain = outcome.surface, outcome.start, ground()
        self.assertTrue(bool(np.all(surface >= terrain)))
        masks = _module("gis.masks.access").load_masks(self.project, self.v01.uid)
        allowed = masks.fill_allowed()
        np.testing.assert_array_equal(surface[~allowed], start[~allowed])
        tower = inside(TOWER)
        np.testing.assert_array_equal(surface[tower], terrain[tower])
        self.assertFalse(bool(np.any(allowed & tower)))
        near = np.zeros_like(tower)
        rows, cols = np.nonzero(tower)
        near[rows.min() - 1:rows.max() + 2, cols.min() - 1:cols.max() + 2] = True
        self.assertTrue(bool(np.any(surface[near & ~tower] > terrain[near & ~tower])),
                        "la plataforma alcanza la torre")
        legal = inside(LEGAL)
        np.testing.assert_array_equal(surface[~legal], terrain[~legal])
        raised = start != terrain
        self.assertEqual(int(np.count_nonzero(raised)), RAISED_CELLS)
        np.testing.assert_array_equal(raised, inside(WATER_BOX) & (terrain < WATER_M))
        self.assertGreater(outcome.design.report.fill_m3, 0.0)
        self.assertEqual(outcome.cut_m3, 0.0)

        self.assertEqual(bpy.ops.geoblender.des_design_fill_only(
            "EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                     FILL_ONLY_TYPE)
        self.assertEqual(status, "done")
        written = self.surfaces.read_surface(self.project, self.dataset,
                                             version_uid=self.v01.uid).values
        np.testing.assert_array_equal(written, surface)
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual(figures["des.fill_only_cut_m3"], 0.0)
        self.assertEqual(figures["des.fill_m3"], outcome.design.report.fill_m3)
        self.assertEqual(figures["des.cut_m3"], 0.0)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name IN (?, ?) AND "
                                   "status = 'current'", self.dataset,
                                   self.dprov.dataset_name("rpt", NAME)), [(2,)])

    def test_c_the_design_in_the_view_and_its_card(self) -> None:
        """RF-014-24, RF-014-29 (M5): «Cargar en la vista» de la superficie da un objeto ``DESIGN``
        «Superficie de diseño …» (el cargador de la 013); la barra N enseña su ficha: la
        envolvente, la superficie de partida, los perfiles y la capa de láminas con su campo, y sus
        cifras; seleccionada, otro «Solo relleno…» propone de partida la de su ficha."""
        loader = self.views.loader_for(self.dataset)
        self.assertEqual((loader.prefix, loader.kind, loader.label),
                         ("des_srf_", KIND, "Design surface"))
        obj = self.loaded(self.dataset)
        self.assertTrue(obj.name.startswith("Superficie de diseño "), obj.name)
        found = self.panels.item_lines(self.project, str(obj.geoblender.dataset_uid))
        texts = [line.text for line in found.lines]
        self.assertEqual(found.title, f"Superficie de diseño · {NAME}")
        self.assertIn(f"Envolvente: «{ENVELOPE}»", texts)
        self.assertIn(f"Superficie de partida: «{self.ground}»", texts)
        self.assertIn(f"Perfiles asignados: base {REST}", texts)
        self.assertIn("Láminas de agua: capa «laminas» · campo «cota»", texts)
        self.assertGreater(len(found.figures), 5, found.figures)
        fake, context, _dialog = self.fake_dialog(selected=(obj,))
        self.cls.invoke(fake, context, None)
        self.assertEqual(fake.start, self.ground)

    def test_d_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-014-29 (RNF-014-05): Esc con el cálculo en marcha, Cancelar la confirmación, un
        nombre vacío y la capa de láminas sin campo no dejan nada (ni operación, ni dato, ni
        cifra, ni temporal); Esc deja el aviso de que no queda nada a medias."""
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_design_fill_only(
                "EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.des_design_fill_only(
            "EXEC_DEFAULT", **self.form(name="Cancelada")), {"FINISHED"})
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)
        for values, text in (({"name": " "}, "Escriba el nombre del diseño «solo relleno»"),
                             ({"name": "Sin campo", "water_field": " "},
                              "Escriba el nombre del campo «Campo de cota» de la capa "
                              "«laminas»")):
            with self.subTest(values=values), self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_design_fill_only("EXEC_DEFAULT", **self.form(**values))
            self.assertIn(text, str(caught.exception))
        self.assertEqual(self.state(), before)

    def test_z_disabling_geoblender_removes_the_command(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta
        (no queda ningún temporal) y quita la orden."""
        self.assertEqual(bpy.ops.geoblender.des_design_fill_only(
            "EXEC_DEFAULT", **self.form(name="Al apagar")), {"FINISHED"})
        self.assertTrue(any(".tmp" in name for name in self.names()))
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, FILL_ONLY_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


if __name__ == "__main__":
    unittest.main()

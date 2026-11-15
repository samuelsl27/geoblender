# SPDX-License-Identifier: GPL-3.0-or-later
"""«Plataforma…» en Blender (spec 015, T15; HU-015-3; RF-015-03, RF-015-28, RF-015-29, RF-015-23 y
RF-015-01; plan 015 §5.3.3 y §5.5; comprobación manual M1).

:class:`GEOBLENDER_OT_des_create_platform` (``geoblender.des_create_platform``, en Diseño ▸ Pistas y
entidades ▸ Entidades; la entrada de R-36 la entrega la T31) calcula con ``design.steps.platform_run`` la
operación ``des.platform`` de la versión activa: la huella y la rasante de una geometría de una capa de
líneas (con su ancho) o de polígonos, aplicadas a su superficie de partida, con el borde que la une con el
terreno. Su diálogo pide el nombre; la capa y la geometría (por su nombre o su ``fid``) con sus campos; **la
cota inicial, la pendiente y el ancho que da la capa, que propone y deja corregir**; **la partida, que propone
la última de la cadena**, y el apoyo; el modo; el borde (ángulo, alcance, factor de malla y métrica); la
tolerancia de contrapendiente y si protege, con su resguardo. Calcular, Crear, Cancelar y Esc son los de las
demás órdenes (``_CalculateAndCreate``): nada se registra hasta Crear. Con una contrapendiente que pasa de su
tolerancia no se crea sin la confirmación expresa.

Un proyecto pequeño por clase (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, el límite legal de
(4, 4) a (56, 56) con 2 m hacia dentro, el perímetro de (2, 2) a (58, 58), un sector con la búsqueda
cerrada y la ladera ``100 + 0,25·y + 0,0625·x``) con una capa de líneas de plataformas: «Carga» (eje de
(20, 30) a (40, 30), 8 m de ancho, rasante de 105 m al 0 %: por debajo de todo el terreno de su huella, que
corta del todo), «Taller», «Rampa» y «Sin ancho» (sin el ancho en la capa). Las pruebas, en el orden de sus
letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
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

from tests.support import blender_ext, step_modals
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

PLATFORM = "geoblender.des_create_platform"
PLATFORM_CLASS = "GEOBLENDER_OT_des_create_platform"
PLATFORM_TYPE = "des.platform"
REASON = "Prueba de la orden «Plataforma…»"
PERSON = "Samuel (IMGA)"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
CELL_M2 = STEP_M * STEP_M
LEGAL = (4.0, 4.0, 56.0, 56.0)
PERIMETER = (2.0, 2.0, 58.0, 58.0)
SECTOR = ("Sector único", (0.0, 0.0, 60.0, 60.0))
CLOSED_AT = "2026-11-15T10:00:00Z"
LAYER = "gis_fea_plataformas"
LAYERS_TYPE = "gis.test_layers"
FEATURES = (
    # nombre, eje local, ancho, cota inicial, pendiente
    ("Carga", ((20.0, 30.0), (40.0, 30.0)), 8.0, 105.0, 0.0),
    ("Taller", ((20.0, 44.0), (40.0, 44.0)), 4.0, 108.0, 0.0),
    ("Rampa", ((20.0, 18.0), (40.0, 18.0)), 4.0, 100.0, 0.0),
    ("Sin ancho", ((20.0, 8.0), (40.0, 8.0)), None, 105.0, 0.0),
)
"""Las geometrías de la capa de plataformas (la de «Sin ancho» no tiene el ancho: se rechaza)."""
LOADING = "Carga"
WORKSHOP = "Taller"
RAMP = "Rampa"
NO_WIDTH = "Sin ancho"
LOADING_LEVEL_M = 105.0
LOADING_CELLS = 40
"""La huella de «Carga» a mano: 4 celdas de través (8 m) por 10 a lo largo (20 m)."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
PROPERTIES = {
    "name": ("Name", "Name of the platform, unique in the active version"),
    "layer": ("Layer", "Layer of the project the platform is taken from: a layer of lines (the axis "
                       "and the width of each platform) or of polygons (the shape of each platform)"),
    "feature": ("Platform of the layer", "Name or number (fid) of the geometry of the layer that is "
                                         "the platform"),
    "start_level_field": ("Start elevation field", "Numeric field of the layer with the elevation of "
                                                   "the platform level at the start of the axis in "
                                                   "metres"),
    "gradient_field": ("Gradient field", "Numeric field of the layer with the gradient of the "
                                         "platform level in %, positive when it rises along the "
                                         "axis"),
    "width_field": ("Width field", "Numeric field of the layer of lines with the width of each "
                                   "platform in metres"),
    "axis_layer": ("Layer of axes", "Layer of lines with the axis of each polygon (none: the main "
                                    "axis of the polygon)"),
    "axis_field": ("Axis link field", "Numeric field of the layer of polygons with the number (fid) "
                                      "of its axis in the layer of axes"),
    "start_level": ("Start elevation (m)", "Elevation of the platform level at the start of the axis "
                                           "in metres: the one of the layer, which you can correct "
                                           "(empty: the one of the layer)"),
    "gradient": ("Gradient (%)", "Gradient of the platform level in %, positive when it rises along the "
                                 "axis: the one of the layer, which you can correct (empty: the one "
                                 "of the layer)"),
    "width": ("Width (m)", "Width of the platform in metres: the one of the layer, which you can "
                           "correct (empty: the one of the layer)"),
    "start": ("Start surface", "Surface the platform starts from: the ground, a design surface or "
                               "the surface of another platform (by default, the last of the chain)"),
    "support": ("Support surface", "Surface the platform rests on, if it rests on one (none: it rests "
                                   "on no other surface)"),
    "mode": ("Mode", "In cut: the platform only lowers the ground to its level; in cut and fill: "
                     "it also raises it where fill is admitted"),
    "edge_angle": ("Edge angle (°)", "Angle of the slope that joins the platform with the ground, in "
                                     "degrees"),
    "reach": ("Reach of the edge (m)", "Farthest distance from the footprint the edge can reach, in "
                                       "metres"),
    "mesh_factor": ("Mesh factor", "Factor of the mesh of the edge (empty: the default value)"),
    "metric": ("Metric", "How the distance to the footprint is measured: the 5×5 chamfer (fast, with "
                         "the scale of the grid) or the exact Euclidean distance"),
    "counter_tolerance": ("Counter-slope tolerance (m)",
                          "How much the longitudinal profile can rise against the sense in which the "
                          "platform level falls before it has to be confirmed, in metres (empty: the "
                          "default value)"),
    "protect": ("Protect", "Declare the footprint a protected zone: the other designs neither cut nor "
                           "fill in it"),
    "guard": ("Guard (m)", "Distance around the footprint that is also protected, in metres; "
                           "required to protect"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone
quien lanza la orden, no los llevan)."""
HIDDEN = ("confirm", "in_steps", "confirm_counterslope")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def path(points: tuple[tuple[float, float], ...]) -> np.ndarray:
    """El camino absoluto de los puntos locales ``points``."""
    return np.array([(WEST + x, SOUTH + y) for x, y in points], dtype=np.float64)


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
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (exacta en binario)."""
    x, y = centers()
    return 100.0 + 0.25 * y + 0.0625 * x


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class CreatePlatformTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera de plataformas, para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t15-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.entities = _module("design.entities")
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
            cls.v01, _revision = store.create_version(conn, cls.project, feature="cantera",
                                                      title="Cantera", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.write_layer()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        cls.layer_before = cls.layer_state()
        cls.refresh()

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y el sector de búsqueda, con su
        búsqueda cerrada, como los dejan las órdenes de la 012."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 15), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                                                 row(types.ACTION_PERIMETER, "Perímetro",
                                                     PERIMETER)],
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
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON, CLOSED_AT)
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
    def write_layer(cls) -> None:
        """La capa ``gis_fea_plataformas`` de líneas con las geometrías de :data:`FEATURES` (``nombre``,
        ``ancho``, ``cota_inicial`` y ``pendiente``; el ancho de «Sin ancho», vacío), como la deja la
        importación de la 006."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        fields = ("ancho", "cota_inicial", "pendiente")
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
                   *(vector.FieldColumn(field, field, "DOUBLE") for field in fields))
        values = {"nombre": tuple(item[0] for item in FEATURES),
                  "ancho": tuple(item[2] for item in FEATURES),
                  "cota_inicial": tuple(item[3] for item in FEATURES),
                  "pendiente": tuple(item[4] for item in FEATURES)}
        parts = tuple(((path(item[1]),),) for item in FEATURES)
        layer = vector.FeatureLayer("line", tuple(range(1, len(FEATURES) + 1)), parts, columns,
                                    values)
        rows = gis_store.feature_rows(layer, srs)
        names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, LAYERS_TYPE, settings={"name": LAYER}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{LAYER}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f"geom {layer.geometry_type}, {names})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)", (LAYER, LAYER, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (LAYER, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{LAYER}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                LAYER, "gis", "vector", datasets.Store.GPKG, LAYER,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de plataformas de la prueba")

    @classmethod
    def layer_state(cls) -> tuple[Any, ...]:
        """La capa de plataformas como está: su registro y todo el contenido de su tabla."""
        with cls.project.read() as conn:
            record = conn.execute("SELECT uid, status, content_sha256 FROM gb_dataset WHERE name = ?",
                                  (LAYER,)).fetchall()
            table = conn.execute(f'SELECT * FROM "{LAYER}" ORDER BY fid').fetchall()
        return record, table

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (superficies, capas y plataformas), leídas de nuevo (un guion no abre
        el diálogo que las lee)."""
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)
        cls.panels.refresh_platform_choices(cls.project)

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
        return self.commands.registered_class(PLATFORM)

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
        """Lo que la orden podría dejar: operaciones, datos, parámetros, cifras y ficheros."""
        return (self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
                self.rows("SELECT name, status FROM gb_dataset ORDER BY name"),
                self.rows("SELECT key, scope, value FROM gb_parameter ORDER BY fid"),
                self.rows("SELECT count(*) FROM gb_figure"), self.names())

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: la plataforma «Carga» de la capa, del terreno, con el borde a 35° y 10 m
        de alcance (la cota inicial, la pendiente y el ancho, los de la capa)."""
        return {"name": LOADING, "layer": LAYER, "feature": LOADING, "start": self.ground,
                "edge_angle": "35", "reach": "10", "in_steps": False, **values}

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana)."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "layer": "", "start": "", "feature": "", "confirm": False,
            "in_steps": False, "confirm_counterslope": False,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, report=lambda kind, text: None, **fields), context, dialog

    def drawn(self, **values: Any) -> list[str]:
        """Los textos que dibuja el diálogo con ``values`` (los de la orden, por defecto)."""
        shown: dict[str, Any] = {
            "name": LOADING, "layer": LAYER, "feature": LOADING, "start_level_field": "cota_inicial",
            "gradient_field": "pendiente", "width_field": "ancho", "axis_layer": "none",
            "axis_field": "eje", "start_level": "", "gradient": "", "width": "", "start": self.ground,
            "support": "none", "mode": "CUT", "edge_angle": "", "reach": "", "mesh_factor": "",
            "metric": "EXACT", "counter_tolerance": "", "protect": False, "guard": "",
            "confirm": False, **values}
        return draw(self.cls, bpy.context, **shown).texts()

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{PLATFORM} no está en marcha")
        return found[0]

    def calculate(self, **values: Any) -> Any:
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.form(**values)),
                         {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create(self, **values: Any) -> set[str]:
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False,
                                                      **values)

    def parameter(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la entidad ``code``: valor, origen, tipo y
        decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, kind, decided_by FROM gb_parameter WHERE key = ? "
            "AND scope = 'version' AND scope_uid = ?",
            f"des.platform.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-015-28, RF-015-01 (plan §5.3.3, §5.5): «Plataforma…» es una orden real de ``des.platform``
        con la puerta de la procedencia y los pasos con Esc; es la clave definitiva del catálogo, de la
        entrada de R-36 que entrega la T31; sus propiedades tienen nombre y descripción en español; su
        diálogo propone un nombre que no repite el de ninguna plataforma, la primera capa y, sin plataformas,
        el terreno de partida; lo dado no cambia; la cota inicial, la pendiente y el ancho que da la capa
        los propone al elegir la geometría (el ``update``: vacíos si la capa no los da o no la tiene) y los
        deja corregir; dibuja los campos del diálogo."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options),
                         (PLATFORM, PLATFORM_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.PLATFORM_COMMAND, PLATFORM)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[PLATFORM_TYPE].commands, (PLATFORM,))
        catalog = self.commands.catalog()
        command = catalog.commands[PLATFORM]
        self.assertEqual((command.label_es, command.entry, command.module),
                         ("Plataforma", "R-36", "des"))
        self.assertFalse(catalog.entries["R-36"].delivered, "la entrega la T31")
        self.assertNotIn("geoblender.des_draw_platform", catalog.commands)
        self.assertFalse(self.commands.is_available(PLATFORM))
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label), self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in HIDDEN:  # las pone quien la lanza: sin nombre ni descripción
            self.assertNotIn("name", cls.__annotations__[prop].keywords)

        fake, context, dialog = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Plataforma")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.layer, fake.start), ("Plataforma 1", LAYER, self.ground))
        given, context, _dialog = self.fake_dialog(
            name="Mía", layer=LAYER, start=self.ground,
            properties=SimpleNamespace(is_property_set=lambda name: name in ("layer", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.start), ("Mía", LAYER, self.ground))

        proposed = SimpleNamespace(layer=LAYER, feature=LOADING, start_level_field="cota_inicial",
                                   gradient_field="pendiente", width_field="ancho", start_level="",
                                   gradient="", width="")
        self.des_ops._propose_values(proposed, None)
        self.assertEqual((proposed.start_level, proposed.gradient, proposed.width),
                         ("105.0", "0.0", "8.0"))
        proposed.feature = "2"  # por su fid: «Taller»
        self.des_ops._propose_values(proposed, None)
        self.assertEqual((proposed.start_level, proposed.width), ("108.0", "4.0"))
        proposed.feature = NO_WIDTH
        self.des_ops._propose_values(proposed, None)
        self.assertEqual((proposed.start_level, proposed.width), ("105.0", ""), "la capa no da el ancho")
        proposed.feature = "No existe"
        self.des_ops._propose_values(proposed, None)
        self.assertEqual((proposed.start_level, proposed.gradient, proposed.width), ("", "", ""))

        shown = self.drawn()
        for heading in ("Nombre", "Capa", "Plataforma de la capa", "Campo de la cota inicial",
                        "Cota de partida (m)", "Pendiente (%)", "Ancho (m)", "Superficie de partida",
                        "Superficie de apoyo", "Modo", "Ángulo del borde (°)", "Alcance del borde (m)",
                        "Factor de malla", "Métrica", "Tolerancia de contrapendiente (m)",
                        "Proteger"):
            self.assertIn(heading, shown)
        self.assertNotIn("Resguardo (m)", shown)
        self.assertIn("Resguardo (m)", self.drawn(protect=True))

    def test_b_calculate_writes_nothing_and_create_registers_the_platform(self) -> None:
        """RF-015-03, RF-015-01, RF-015-02, RF-015-04, M1: Calcular desde un guion deja el cálculo abierto con
        su resumen (la huella, la rasante, el desmonte y el relleno de la huella y del borde y «sin
        contrapendientes», en los dos idiomas, con su título) y solo el temporal; nada en el proyecto. Crear
        registra ``des.platform`` hecha en V01 con ``des_psf_`` (la huella a su rasante, el resto del
        terreno), la tabla y el informe, las cifras CALCULADO y los parámetros de la entidad como filas de la
        versión (la cota inicial, la pendiente y el ancho copiados de la capa con su origen) de quien tiene
        abierto el proyecto; la capa no se toca."""
        before = self.state()
        held = self.calculate()
        self.assertEqual((held.op_type, held.name, held.version), (PLATFORM_TYPE, LOADING, "V01"))
        self.assertEqual(held.entity.code, "PLT-001")
        after = self.state()
        self.assertEqual(after[:4], before[:4], "calcular no registra nada")
        (temporary,) = sorted(set(after[4]) - set(before[4]))
        self.assertIn(".tmp", temporary)
        self.assertEqual(self.view.summary_title, f"Plataforma «{LOADING}» en V01")
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        outcome = held.outcome
        footprint = outcome.footprint
        self.assertEqual(footprint.cell_count, LOADING_CELLS)
        self.assertEqual(summary[0][0], f"Plataforma «{LOADING}» (PLT-001): huella de "
                                        f"{int(footprint.cell_count * CELL_M2)} m² en "
                                        f"{LOADING_CELLS} celdas · eje de 20,0 m")
        self.assertTrue(summary[1][0].startswith("Rasante: cota de 105"), summary[1])
        self.assertTrue(summary[2][0].startswith("Huella: desmonte"), summary[2])
        self.assertIn("Sin contrapendientes (tolerancia de 0,10 m)", [text for text, _alert in summary])
        cut = float(((ground() - LOADING_LEVEL_M) * CELL_M2)[footprint.window][footprint.cells].sum())
        self.assertAlmostEqual(outcome.applied.cut_m3, cut, delta=1e-9 * cut)
        self.assertEqual(outcome.applied.fill_m3, 0.0, "en corte no rellena")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual([line.name for line in self.view.summary][0],
                         f"Platform «{LOADING}» (PLT-001): footprint {int(footprint.cell_count * CELL_M2)}"
                         f" m² in {LOADING_CELLS} cells · axis 20.0 m")
        self.assertEqual(self.view.summary_title, f"Platform «{LOADING}» in V01")
        self.i18n.set_language("es")
        self.panels.show_summary(held)

        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                     PLATFORM_TYPE)
        self.assertEqual(status, "done")
        psf = self.dprov.dataset_name("psf", LOADING)
        written = self.surfaces.read_surface(self.project, psf, version_uid=self.v01.uid).values
        inside = np.zeros(written.shape, dtype=bool)
        inside[footprint.window] = footprint.cells
        np.testing.assert_array_equal(written[inside], np.full(int(inside.sum()), LOADING_LEVEL_M))
        self.assertTrue((written <= ground()).all(), "en corte no sube ninguna celda")
        np.testing.assert_array_equal(written[~inside & (ground() <= LOADING_LEVEL_M)],
                                      ground()[~inside & (ground() <= LOADING_LEVEL_M)])
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertAlmostEqual(figures["des.plat_cut_m3"], cut, delta=1e-9 * cut)
        self.assertEqual(figures["des.plat_area_m2"], footprint.cell_count * CELL_M2)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND "
                                   "name IN (?, ?, ?)", psf, self.dprov.dataset_name("epr", LOADING),
                                   self.dprov.dataset_name("prp", LOADING)), [(3,)])
        for param, value, field in (("start_level_m", 105.0, "cota_inicial"),
                                    ("gradient_pct", 0.0, "pendiente"), ("width_m", 8.0, "ancho")):
            with self.subTest(parametro=param):
                found = self.parameter("PLT-001", param)
                self.assertEqual(found[0], value)
                self.assertEqual(found[1], f"capa «{LAYER}», campo «{field}», entidad «{LOADING}»")
                self.assertEqual((found[2], found[3]), ("ADOPTADO", self.project.session.user_host))
        self.assertEqual(self.parameter("PLT-001", "start")[0], self.ground)
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de origen no se toca")
        entry = self.entities.registry(self.project, self.v01.uid).get("PLT-001")
        self.assertEqual((entry.record.name, str(entry.record.state)), (LOADING, "current"))

    def test_c_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-015-29, RF-015-03, RF-015-08 (RNF-014-05): Esc **a mitad** del cálculo (con su temporal ya
        escrito), Cancelar la confirmación y lo que falta o se rechaza (el nombre, la geometría que no
        está, el ancho que la capa no da, el ángulo sin valor, una partida que ya ocupa otra plataforma) no
        dejan nada: ni operación, ni dato, ni parámetro, ni cifra, ni temporal; Esc dice que no queda nada a
        medias."""
        self.refresh()
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_platform(
                "EXEC_DEFAULT", **self.form(name="Esc", feature=WORKSHOP, start="entity:PLT-001",
                                            in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S  # un paso por evento
        for _ in range(step_modals.MAX_EVENTS):
            self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
            if any(".tmp" in name for name in self.names()):
                break
        else:
            self.fail("el cálculo no llegó a escribir su temporal")
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        self.calculate(name="Cancelada", feature=WORKSHOP, start="entity:PLT-001")
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, text in (
                ({"name": " "}, "Escriba el nombre de la plataforma"),
                ({"feature": " "}, "Escriba el nombre o el número de la plataforma en su capa"),
                ({"feature": "No existe"}, "No existe"),
                ({"feature": NO_WIDTH}, "ancho"),
                ({"feature": WORKSHOP, "edge_angle": ""}, "edge_angle_deg"),
                ({"feature": WORKSHOP, "edge_angle": "abc"}, "«abc» no es un número")):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.form(
                        **{"name": "Rechazada", "start": "entity:PLT-001", **changes}))
                self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)
        with self.assertRaises(RuntimeError) as taken:  # el terreno ya es la partida de «Carga»
            bpy.ops.geoblender.des_create_platform(
                "EXEC_DEFAULT", **self.form(name="Otra", feature=WORKSHOP))
        self.assertIn(LOADING, str(taken.exception))
        self.assertEqual(self.state(), before)

    def test_d_the_start_is_the_last_of_the_chain_and_the_values_are_corrected_in_the_dialog(
            self) -> None:
        """RF-015-04, RF-015-19, RF-015-01 (plan §5.3.3, §5.2.1): con una plataforma en la versión, el
        diálogo propone de partida **la última de la cadena** (``entity:PLT-001``) y un nombre nuevo; la
        persona corrige la cota inicial (con coma decimal) y el ancho de la capa y deja la pendiente, que
        es la misma: se copian como parámetros de la versión, los corregidos con el origen del diálogo y el
        que no cambió con el de la capa; la plataforma queda encadenada a la primera, que sigue al día, y su
        superficie solo baja la de la primera; la última de la cadena pasa a ser la nueva; la capa no se toca."""
        self.refresh()
        fake, context, dialog = self.fake_dialog()
        self.cls.invoke(fake, context, None)
        self.assertEqual((fake.name, fake.layer, fake.start),
                         ("Plataforma 2", LAYER, "entity:PLT-001"))
        before = self.state()
        held = self.calculate(name=WORKSHOP, feature=WORKSHOP, start="entity:PLT-001",
                              start_level="107,5", gradient="0", width="5", reach="6")
        self.assertEqual(held.entity.code, "PLT-002")
        self.assertEqual(held.entity.start_surface, self.dprov.dataset_name("psf", LOADING))
        self.assertFalse(held.needs_confirmation)
        self.assertEqual(self.state()[:4], before[:4])
        fake_ok = operator_self(self.cls, confirm_counterslope=False)
        self.cls._confirmation(fake_ok, context)
        self.assertEqual(dialog.call_args.kwargs["confirm_text"].split(" ")[0], "Crear")
        self.assertFalse(fake_ok.confirm_counterslope)
        self.assertEqual(self.create(), {"FINISHED"})
        value, source, kind, decider = self.parameter("PLT-002", "start_level_m")
        self.assertEqual((value, kind, decider), (107.5, "ADOPTADO", self.project.session.user_host))
        self.assertEqual(source, f"diálogo de «Plataforma…», entidad «{WORKSHOP}»")
        self.assertEqual(self.parameter("PLT-002", "width_m")[:2],
                         (5.0, f"diálogo de «Plataforma…», entidad «{WORKSHOP}»"))
        self.assertEqual(self.parameter("PLT-002", "gradient_pct")[:2],
                         (0.0, f"capa «{LAYER}», campo «pendiente», entidad «{WORKSHOP}»"))
        self.assertEqual(self.parameter("PLT-002", "start")[0], "entity:PLT-001")
        registry = self.entities.registry(self.project, self.v01.uid)
        self.assertEqual([(entry.record.code, str(entry.record.state)) for entry in registry],
                         [("PLT-001", "current"), ("PLT-002", "current")])
        self.assertEqual([record.code for record in self.entities.chain_tails(registry.records)],
                         ["PLT-002"])
        first = self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", LOADING),
                                           version_uid=self.v01.uid).values
        second = self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", WORKSHOP),
                                            version_uid=self.v01.uid).values
        self.assertTrue((second <= first).all(), "sobre la superficie de la primera solo baja")
        self.assertTrue((second < first).any())
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de origen no se toca")
        self.refresh()
        self.assertEqual(self.panels.platform_default_start(), "entity:PLT-002")
        proposal, context, _dialog = self.fake_dialog()
        self.cls.invoke(proposal, context, None)
        self.assertEqual((proposal.name, proposal.start), ("Plataforma 3", "entity:PLT-002"))

    def test_e_the_counter_slope_is_not_created_without_the_express_confirmation(self) -> None:
        """RF-015-23 (E1), RF-015-03, M1: «Rampa», con la cota inicial y la pendiente que corrige la persona
        (106,5 m al −5 %: la rasante cae hacia el este, el terreno sube), tiene una contrapendiente: el
        resumen la avisa en ámbar y el botón de crear dice «Confirmar la contrapendiente y crear» (pulsarlo es
        la confirmación expresa); sin ella, desde un guion, Crear se rechaza (el motivo), no escribe nada y el
        cálculo sigue abierto; confirmada, se crea y deja en los ajustes de la operación cuánto subía, en qué
        abscisa, quién lo confirmó y cuándo."""
        self.refresh()
        before = self.state()
        held = self.calculate(name=RAMP, feature=RAMP, start="entity:PLT-002", start_level="106.5",
                              gradient="-5", reach="6")
        self.assertTrue(held.needs_confirmation)
        profile = held.outcome.profile
        worst = profile.worst
        self.assertIsNotNone(worst)
        amount, abscissa = float(profile.rise_m[worst]), float(profile.chainage_m[worst])
        self.assertGreater(amount, 0.1)
        alerts = [line.name for line in self.view.summary if line.alert]
        self.assertTrue(any("contrapendiente" in text and "confirme" in text for text in alerts), alerts)
        self.assertNotIn("Sin contrapendientes", " ".join(line.name for line in self.view.summary))
        self.assertEqual(self.state()[:4], before[:4])

        with self.assertRaises(RuntimeError) as caught:  # sin la confirmación expresa
            self.create()
        self.assertIn("no se crea sin su confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), window_manager=SimpleNamespace(
            invoke_props_dialog=dialog))
        asked = operator_self(self.cls, confirm_counterslope=False)
        self.cls._confirmation(asked, context)
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar la contrapendiente y crear")
        self.assertTrue(asked.confirm_counterslope)
        self.assertEqual(dialog.call_args.kwargs["title"], f"Plataforma «{RAMP}» en V01")
        self.assertEqual(self.create(confirm_counterslope=True), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND "
                                   "settings LIKE ?", PLATFORM_TYPE, f"%{RAMP}%")
        recorded = json.loads(settings)["counterslope_confirmed"]
        self.assertEqual((recorded["amount_m"], recorded["abscissa_m"]), (amount, abscissa))
        self.assertEqual(recorded["decided_by"], self.project.session.user_host)
        self.assertRegex(recorded["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        entry = self.entities.registry(self.project, self.v01.uid).get("PLT-003")
        self.assertEqual((entry.record.name, str(entry.record.state)), (RAMP, "current"))

    def test_f_the_command_is_disabled_with_its_reason(self) -> None:
        """RF-015-28 (M1): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión
        activa no editable (V02 SUPERADO: «V02 está en estado SUPERADO: …», que dice también su descripción),
        la orden sale desactivada con su motivo y no se puede lanzar; con V01 en escritura, activa."""
        messages: list[str] = []
        cls = self.cls
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(bpy.ops.geoblender.des_create_platform.poll())

        def poll() -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(
                    lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_create_platform.poll())
            before = self.state()
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.form(name="No debe"))
            self.assertEqual(self.state(), before)
        self.assertTrue(poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid),
                         {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertFalse(bpy.ops.geoblender.des_create_platform.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid),
                         {"FINISHED"})
        self.assertTrue(poll())

    def test_z_disabling_geoblender_removes_the_command_and_leaves_no_temporary(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta (no queda
        ningún temporal) y quita la orden."""
        self.refresh()
        self.calculate(name="Al apagar", feature=WORKSHOP, start="entity:PLT-003")
        self.assertTrue(any(".tmp" in name for name in self.names()))
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, PLATFORM_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


if __name__ == "__main__":
    unittest.main()

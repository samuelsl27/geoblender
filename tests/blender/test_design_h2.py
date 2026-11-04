# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de la spec 013 (T29): E1 a E5 con las **órdenes reales** (``bpy.ops.geoblender.…``) en
``blender -b --python-exit-code 1`` con un perfil temporal, sobre el proyecto del diseño (el del hito H1,
``tests/referencia/des/test_h1_flow.py``: el sitio de 160 × 160 celdas de 2 m, V01 y V02, las cinco
restricciones y los dos sectores de la 012), y con las mismas cifras que el H1.

Una sola historia, en el orden de las letras (el proyecto es de la clase, como en ``VersionsStoryTest``):
las órdenes presentan y lanzan lo que ya hace el dominio, y aquí se comprueba que dan lo mismo que las
funciones del H1, con cálculos a mano o las rejillas releídas del proyecto, nunca con lo que devolvió la
función que calculó.

- **a** (RF-013-18, RF-013-19): los perfiles ``EXPL_10_60_6`` y ``REST_5_35_6`` con sus derivados
  (avance 11,77 m y talud general 40,34°; 13,14 m y 20,83°).
- **b** (E5, RF-013-01 a 03, CE-013-07): la vista previa de las semillas del fondo del hueco (2.800 celdas,
  dominio de 8.540, el sector 2 pendiente), de la ladera entera (17.060 celdas fuera del dominio) y de V02
  (sin máscaras); no escribe nada.
- **c** (CE-013-06, RF-013-05): el cálculo se niega con un sector sin búsqueda de intocables y no deja nada.
- **d** (D-14, RF-013-33): Esc a mitad no deja nada, tampoco el escalonado que esperaba.
- **e** (E1, CE-013-01, CE-013-03): el hueco que sube desde un fondo y su escalonado en corte, calculados y
  creados con las órdenes; la envolvente y las bermas son las del H1.
- **f** (E2, CE-013-01): la envolvente descendente exacta desde el borde del límite legal es la distancia
  a mano entre centros de celda.
- **g** (E3, CE-013-03): el relleno de berma primero de una montera de semillas.
- **h** (E4, CE-013-04, CE-013-05, V02): el sector con talud general de 10,6° tiene su berma de 19,5765 m.
- **i** (CE-013-08): congelar V01.r1 lista las superficies de diseño sin verificar y pide aceptarlas.
- **j** (CE-013-08): cambiar el ancla de ``EXPL_10_60_6`` solo en V01 deja obsoleto solo el escalonado de
  corte, «Recalcular lo obsoleto» lo rehace sin pedir confirmación y reproducir V01.r1 da lo congelado.
- **k** (RF-013-34): exportar las tres rejillas del hueco a GeoTIFF sin escribir en el proyecto.
- **l** (CE-013-06): «Verificar un diseño por recinto…» da 0 m³ en todos los recintos y una celda movida en
  la torre hace fallar solo la torre.
- **m** (CE-013-06): al cambiar una restricción, las operaciones y las superficies quedan obsoletas con su
  causa, en las dos versiones; lo congelado no cambia.

Ninguna llamada del modal pasa de 0,2 s de CPU (RNF-013-07, sin la transacción final de «Crear», que se
mide aparte). Un proyecto por clase y la extensión sin importar otra vez (RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import importlib
import json
import math
import tempfile
import time
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
from tests.support.trees import remove_tree

OPEN = "geoblender.des_compute_envelope"
EXPORT = "geoblender.des_export_design_grid"
RECOMPUTE = "geoblender.core_recompute_stale"
VERIFY = "geoblender.res_verify_constraints"
REPRODUCE = "geoblender.core_reproduce_version"
VIEW_PROPERTY = "geoblender_design"
ENVELOPE_TYPE = "des.envelope"
STEPPED_TYPE = "des.stepped_design"
REASON = "Prueba del hito H2 de la 013"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
CLOSED_AT = "2026-11-03T10:00:00Z"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 20_000

# El sitio del H1 (``tests.support.constraints_fixtures``): celdas de 2 m, 160 × 160, en coordenadas
# locales desde BASE; aquí solo los números, porque esas ayudas cargan una segunda copia del paquete y
# dentro de Blender no se importan (docs/trampas.md §4).
BASE = (699_700.0, 4_399_700.0)
STEP_M = 2.0
CELLS = 160
WINDOW = (BASE[0] - 20.0, BASE[1] - 100.0, BASE[0] + 300.0, BASE[1] + 220.0)
START_Z = 650.0
LEGAL_LIMIT_LOCAL = ((0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0), (0.0, 0.0))
PERIMETER_LOCAL = ((20.0, 20.0), (180.0, 20.0), (180.0, 50.0), (268.0, 50.0), (268.0, 150.0),
                   (180.0, 150.0), (180.0, 180.0), (20.0, 180.0), (20.0, 20.0))
TOWER_LOCAL = (186.0, 100.0)
POND_LOCAL = (60.0, 80.0, 120.0, 130.0)
DITCH_LOCAL = ((40.0, 150.0), (100.0, 150.0))
SECTORS_LOCAL = {"Sector 1": (20.0, 20.0, 90.0, 180.0), "Sector 2": (110.0, 20.0, 180.0, 180.0)}
SEARCH_DISTANCE_M = 25.0
DOMAIN_CELLS = 8540
"""El dominio de trabajo de V01: 6.840 celdas del dominio por defecto y 1.700 de la franja de solo
relleno."""
PIT_SEEDS = 35 * 80
"""Las semillas del fondo del hueco: el sector 1 es de 35 × 80 celdas de 2 m."""
SCALE = 0.98644
"""El factor del *chamfer* 5×5 (ADR-0014)."""
PROFILE_ANCHOR = 125.0
SECTOR_SLOPE_DEG = 10.6
BOTTOM_M = 630.0
MOUND_TOP_M = 660.0
NEW_ANCHOR_M = 127.0
TOLERANCE_FACE_DEG = 1.0
EXPL = "EXPL_10_60_6"
REST = "REST_5_35_6"
EXPL_CODE = "expl_10_60_6"
REST_CODE = "rest_5_35_6"


def tan_deg(degrees: float) -> float:
    return math.tan(math.radians(degrees))


def general_deg(height: float, face_deg: float, berm: float) -> float:
    """El talud general (°) de un perfil, a mano: ``atan(h / (h/tan α + B))``."""
    return math.degrees(math.atan(height / (height / tan_deg(face_deg) + berm)))


EXPL_GENERAL_DEG = general_deg(10.0, 60.0, 6.0)
REST_GENERAL_DEG = general_deg(5.0, 35.0, 6.0)
IMPOSED_BERM_M = 5.0 / tan_deg(SECTOR_SLOPE_DEG) - 5.0 / tan_deg(35.0)
"""La berma del sector de 10,6° con ``REST_5_35_6``, a mano (19,5765237 m)."""


def absolute(points: Any) -> np.ndarray:
    """Los puntos locales (m desde BASE) en coordenadas absolutas, float64 ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) + np.asarray(BASE)


def rectangle(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local dado."""
    return absolute([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)])


def col_of(x_local: float) -> int:
    """La columna de la celda cuyo centro está en ``x`` local (m): el sitio parte de x = −20."""
    return int(round((x_local + 20.0) / STEP_M - 0.5))


def row_of(y_local: float) -> int:
    """La fila de la celda cuyo centro está en ``y`` local (m): el sitio parte de y = 220."""
    return int(round((220.0 - y_local) / STEP_M - 0.5))


def incline_pairs(grid: np.ndarray, inside: np.ndarray) -> float:
    """La mayor inclinación (°) entre celdas vecinas a 8 vecinos que están **las dos** en ``inside``."""
    worst = 0.0
    rows, cols = grid.shape
    for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
        first = (slice(0, rows - d_row), slice(max(0, -d_col), cols - max(0, d_col)))
        second = (slice(d_row, rows), slice(max(0, d_col), cols - max(0, -d_col)))
        both = inside[first] & inside[second]
        rise = np.abs(grid[first] - grid[second]) / (STEP_M * math.hypot(d_row, d_col))
        if both.any():
            worst = max(worst, float(rise[both].max()))
    return math.degrees(math.atan(worst))


def moved_incline(grid: np.ndarray, moved: np.ndarray) -> float:
    """La mayor inclinación (°) de una celda con movimiento a cualquiera de sus 8 vecinas: lo que mide
    el informe, recalculado aparte."""
    rows, cols = grid.shape
    padded = np.pad(grid, 1, constant_values=np.nan)
    worst = 0.0
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            side = padded[1 + d_row:1 + d_row + rows, 1 + d_col:1 + d_col + cols]
            with np.errstate(invalid="ignore"):
                rise = np.abs(grid - side) / (STEP_M * math.hypot(d_row, d_col))
            pick = moved & np.isfinite(rise)
            if pick.any():
                worst = max(worst, float(rise[pick].max()))
    return math.degrees(math.atan(worst))


def plateaus(row: np.ndarray, anchor: float, height: float, first: int, last: int) -> list[int]:
    """Las anchuras, en celdas, de los tramos planos de una fila en una cota ``anchor + n·h`` (a ≤ 10⁻⁹ m)
    que están enteros entre las columnas ``first`` y ``last`` y limitados a los dos lados por celdas
    que no lo son."""
    levels = (row - anchor) / height
    flat = np.abs(levels - np.round(levels)) * height <= 1e-9
    found: list[int] = []
    column = first
    while column <= last:
        if flat[column] and not flat[column - 1]:
            end = column
            while end < flat.size and flat[end]:
                end += 1
            if end <= last + 1 and end < flat.size and not flat[end]:
                found.append(end - column)
            column = end
        else:
            column += 1
    return found


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class DesignH2Test(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto del diseño para toda la clase (las pruebas, en el
    orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-h2-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.versions_ops = _module("bl.ops.versions")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cparams = _module("core.constraints.params")
        cls.cprov = _module("core.constraints.provenance")
        cls.params = _module("core.params")
        cls.access = _module("gis.masks.access")
        cls.compose = _module("design.compose")
        cls.dmodel = _module("design.model")
        cls.dsteps = _module("design.steps")
        cls.dprov = _module("design.provenance")
        cls.reader = _module("gis.geotiff.reader")
        cls.graph = _module("core.provenance.graph")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=WINDOW, grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="mascaras",
                                                      title="Máscaras", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.codes = cls.declare()
        cls.declare_sectors()
        cls.close_search("sector_1", 1)  # el 2, pendiente: lo cierra la prueba c
        cls.start_name = cls.write_grid("partida", np.full((CELLS, CELLS), START_Z))
        cls.layers_type = cls.register_layers_type()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}
        for name, values in ((EXPL, ("10", "60", "6", "125")), (REST, ("5", "35", "6", "125"))):
            height, face, berm, anchor = values
            assert bpy.ops.geoblender.des_save_bench_profile(
                name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
                scope="PROJECT", height=height, face=face, berm=berm, anchor=anchor) == {"FINISHED"}
        cls.refresh_lists()
        cls.design = _module("bl.draw.design")

    # --- El proyecto del diseño: lo que escribe la plantilla del H1, con las operaciones reales ---

    @classmethod
    def declare(cls) -> dict[str, str]:
        """Las cinco restricciones del sitio con los parámetros del H1 (``constraints_project``): el
        límite legal (10 m hacia dentro), el perímetro de actuación con su lóbulo fuera del límite, la
        torre (6 m en el proyecto y 8 m solo en V01), la balsa «sin relleno» (0 m) y la cuneta «sin
        corte» (4 m). El código de cada una, por su nombre."""
        m, kinds, types, par = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType, \
            cls.cmodel.ConstraintParam

        def row(ctype: Any, name: str, kind: Any, part: np.ndarray, priority: int = 0) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kind,
                parts=((part,),), priority=priority, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 3), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kind), fid=0)

        found: dict[str, str] = {}
        for item, values in (
                (row(types.LEGAL_LIMIT, "Concesión", kinds.POLYGON, absolute(LEGAL_LIMIT_LOCAL)),
                 {par.ACTIVE: True, par.BUFFER_IN: 10.0}),
                (row(types.ACTION_PERIMETER, "Perímetro", kinds.POLYGON, absolute(PERIMETER_LOCAL)),
                 {par.ACTIVE: True}),
                (row(types.UNTOUCHABLE, "Torre", kinds.POINT, absolute([TOWER_LOCAL]), 10),
                 {par.ACTIVE: True, par.BUFFER_OUT: 6.0}),
                (row(types.NO_FILL, "Balsa", kinds.POLYGON, rectangle(*POND_LOCAL)),
                 {par.ACTIVE: True, par.BUFFER_OUT: 0.0}),
                (row(types.NO_CUT, "Cuneta", kinds.LINE, absolute(DITCH_LOCAL)),
                 {par.ACTIVE: True, par.BUFFER_OUT: 4.0})):
            declaration = cls.cprov.ParamDeclaration(
                values=values, source="Valores sintéticos de prueba", decided_by=PERSON,
                reason=REASON)
            edited = cls.cprov.edit_constraints(cls.project, [item], params=declaration,
                                                srs_id=cls.project.record.crs_epsg)
            found[item.ctype.value] = str(edited.constraints[0].code)
        store = cls.params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:  # la torre, a 8 m solo en V01
            store.create(conn, cls.cparams.buffer_out_key(found["untouchable"]), 8.0,
                         kind="HIPÓTESIS", source="Valores sintéticos de prueba",
                         source_kind="document", decided_by=PERSON, reason=REASON,
                         version=cls.v01.code)
        return found

    @classmethod
    def declare_sectors(cls) -> None:
        """Los dos sectores de búsqueda (``core_sector``), como los dejará «Declarar de nuevo desde una
        capa…»."""
        sectors = tuple(
            cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name,
                              (rectangle(*box),))
            for index, (name, box) in enumerate(SECTORS_LOCAL.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str, minutes: int) -> None:
        """Cierra la búsqueda de intocables de un sector (con su huella), como hará la orden de la 012."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(f"search{minutes}{'0' * 25}", handle.uid, code,
                                         cls.cstore.sector_sha256(sector), SEARCH_DISTANCE_M, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto con ``values`` (como la deja «Rejilla del proyecto desde un MDT»,
        ``gis.resample``); el nombre de su dato."""
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
    def register_layers_type(cls) -> str:
        """El tipo de operación de prueba que escribe las capas de polígonos (hace lo que la importación
        de la 006), registrado hasta el final de la clase."""
        contract = _module("core.provenance.contract")
        found = "gis.test_layers"
        contract.register_operation(contract.OperationDef(found, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, found)
        return found

    @classmethod
    def write_layer(cls, name: str, rings: list[list[np.ndarray]]) -> None:
        """Una capa ``gis_fea_…`` de UN polígono con los anillos absolutos dados (el primero, el
        exterior), como la deja la importación de la 006; las listas del diálogo, al día."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        layer = vector.FeatureLayer(
            "polygon", (1,), (((tuple(np.asarray(ring, dtype=np.float64) for ring in rings)),),),
            (vector.FieldColumn("nombre", "nombre", "TEXT"),), {"nombre": ("Entidad 1",)})
        rows = gis_store.feature_rows(layer, srs)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, cls.layers_type, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f'geom {layer.geometry_type}, "nombre" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" (fid, geom, "nombre") VALUES (?, ?, ?)', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de prueba")
        cls.refresh_lists()

    @classmethod
    def refresh_lists(cls) -> None:
        """Las listas de los diálogos (perfiles, sectores, superficies, zonas y capas), leídas de nuevo
        (un guion no abre el diálogo que las lee)."""
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no pasa a la siguiente
        if self.design.enabled():
            self.design.disable()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def root(self) -> Path:
        return Path(self.project.root)

    @property
    def area(self) -> float:
        return STEP_M * STEP_M

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operations(self, op_type: str, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, superseded_by FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", op_type)
        return self.rows(sql + " AND status = ? ORDER BY fid", op_type, status)

    def des_operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'des.%'")[0][0])

    def datasets(self, version: Any = None) -> list[str]:
        """Los datos vivos de la 013 de ``version`` (por defecto V01), sin la tabla de los perfiles."""
        target = self.v01 if version is None else version
        return [name for (name,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name LIKE 'des!_%' ESCAPE '!' AND status = "
            "'current' AND name <> 'des_bench_profile' AND version_uid = ? ORDER BY name",
            target.uid)]

    def names(self) -> list[str]:
        """Todos los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def temporaries(self) -> list[str]:
        return [name for name in self.names() if ".tmp" in name]

    def hashes(self) -> dict[str, str]:
        """Cada fichero del proyecto con su huella (lo que una orden que solo lee no cambia)."""
        return {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                for name in self.names()}

    def figures_of(self, op_uid: str) -> dict[str, float]:
        return {key: value for key, value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", op_uid)}

    def last_done(self, op_type: str, name: str, version: Any = None) -> str:
        """El uid de la última operación hecha de ``op_type`` y ``name`` (sin sustituir)."""
        target = self.v01 if version is None else version
        found = [uid for uid, settings in self.rows(
            "SELECT o.uid, o.settings FROM gb_operation AS o LEFT JOIN gb_revision AS r ON r.uid = "
            "o.revision_uid WHERE o.op_type = ? AND o.status = 'done' AND o.superseded_by IS NULL "
            "AND r.version_uid = ? ORDER BY o.fid", op_type, target.uid)
            if json.loads(settings)["name"] == name]
        self.assertEqual(len(found), 1, f"{op_type} «{name}» en {target.code}: {found}")
        return str(found[0])

    def grid_of(self, family: str, name: str, version: Any = None) -> np.ndarray:
        """Las celdas de la rejilla ``family`` de la operación ``name`` tal como están en el proyecto."""
        target = self.v01 if version is None else version
        ((locator,),) = self.rows(
            "SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current' AND version_uid "
            "= ?", self.dprov.dataset_name(family, name), target.uid)
        return np.array(self.reader.read_geotiff(self.root.joinpath(*locator.split("/")),
                                                 max_cells=10 ** 7).values, dtype=np.float64)

    def dataset_uid(self, family: str, name: str, version: Any = None) -> str:
        target = self.v01 if version is None else version
        ((uid,),) = self.rows(
            "SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current' AND version_uid = ?",
            self.dprov.dataset_name(family, name), target.uid)
        return str(uid)

    def report_codes(self, name: str, version: Any = None) -> list[str]:
        """Los códigos de los avisos y notas del informe del escalonado ``name``."""
        target = self.v01 if version is None else version
        table = self.dprov.dataset_locator(self.dprov.REPORT_TABLE, name, target.code)
        return [json.loads(note)["code"] for quantity, note in self.rows(
            f'SELECT quantity, note FROM "{table}" ORDER BY fid') if quantity in ("warning", "note")]

    def berm_rows(self, name: str, version: Any = None) -> list[tuple[Any, ...]]:
        target = self.v01 if version is None else version
        table = self.dprov.dataset_locator(self.dprov.BERM_TABLE, name, target.code)
        return self.rows(f'SELECT sector, profile, level_m, cells, area_m2, anchor_m, anchor_diff_m '
                         f'FROM "{table}" ORDER BY fid')

    def masks(self, version: Any = None) -> Any:
        target = self.v01 if version is None else version
        return self.access.load_masks(self.project, target.uid)

    def start_values(self) -> np.ndarray:
        return np.full((CELLS, CELLS), START_Z)

    def moved_volume(self, start: np.ndarray, design: np.ndarray, sign: float) -> float:
        """El volumen (m³) que se desmonta (``sign`` = 1) o se rellena (−1) entre ``start`` y
        ``design``, a mano, en las celdas que mueven más del espesor mínimo de la 012 (0,02 m)."""
        moved = sign * (start - design)
        return float(np.sum(moved[moved > 0.02]) * self.area)

    # --- El modal de la orden: un evento del temporizador cada vez ---------------------------------

    def running(self, command: str = OPEN) -> Any:
        """El modal de ``command`` en marcha (el único con pasos)."""
        cls = self.commands.registered_class(command)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{command} no está en marcha")
        return found[0]

    def drive(self, operator: Any, *, stop_after: int | None = None,
              until: Any = None) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba (o ``stop_after`` eventos, o
        hasta que ``until()`` sea verdad): su final y lo que duró cada llamada (s de CPU del proceso)."""
        calls: list[float] = []
        for index in range(MAX_EVENTS):
            if stop_after is not None and index == stop_after:
                return {"RUNNING_MODAL"}, calls
            if until is not None and until():
                return {"RUNNING_MODAL"}, calls
            started = time.process_time()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.process_time() - started)
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("el cálculo no acaba")

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: por defecto, el hueco de E1 (semillas a 630 m en el sector 1,
        envolvente ascendente con el talud general de ``EXPL_10_60_6``, *chamfer* 5×5)."""
        return {"name": "Hueco", "seeds_from": "FIXED", "zone": "sector:sector_1",
                "elevation": "630", "direction": "UP", "metric": "CHAMFER5",
                "slope_mode": "CONSTANT", "slope": repr(EXPL_GENERAL_DEG), "in_steps": True,
                **values}

    def start(self, **values: Any) -> Any:
        """Lanza la orden desde la interfaz (por pasos) y devuelve el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT",
                                                                     **self.form(**values)),
                             {"RUNNING_MODAL"})
        self._last = self.running()
        return self._last

    def calculate(self, **values: Any) -> tuple[set[str], list[float], Any]:
        """Calcula por pasos hasta el final (la confirmación, sustituida: sin ventana el temporizador no
        corre): el final del modal, lo que duró cada llamada y el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT",
                                                                     **self.form(**values)),
                             {"RUNNING_MODAL"})
            modal = self._last = self.running()
            state, calls = self.drive(modal)
        self.assertEqual(ask.call_count, 1 if state == {"FINISHED"} else 0)
        return state, calls, modal

    def create(self) -> set[str]:
        """«Crear»: la misma orden con ``confirm=True`` (con el escalonado encadenado, el modal)."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            return bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT", confirm=True,
                                                           in_steps=True)

    def make(self, stepped: bool = False, **values: Any) -> list[float]:
        """Calcular y Crear con las órdenes (y, con ``stepped``, también su escalonado): lo que duró cada
        llamada del modal."""
        state, calls, _modal = self.calculate(stepped=stepped, **values)
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.create(), {"RUNNING_MODAL"} if stepped else {"FINISHED"})
        if stepped:
            state, more = self.drive(self.running())
            self.assertEqual(state, {"FINISHED"})
            calls += more
            self.assertEqual(self.create(), {"FINISHED"})
        return calls

    # --- a: los perfiles ----------------------------------------------------------------------

    def test_a_the_profiles_have_their_derived_values(self) -> None:
        """RF-013-18, RF-013-19, RF-013-20 (M2): los perfiles ``EXPL_10_60_6`` y ``REST_5_35_6``,
        creados con la orden como ADOPTADO del proyecto, quedan en la vista con sus derivados a mano
        (avance 11,77 m y talud general 40,34°; 13,14 m y 20,83°) y su cifra de cada parámetro
        en el proyecto."""
        shown = {item.name: item for item in self.view.profiles}
        self.assertEqual(sorted(shown), [EXPL, REST])
        self.assertEqual((shown[EXPL].code, shown[REST].code), (EXPL_CODE, REST_CODE))
        number = self.i18n.format_number
        for name, height, face, berm, wanted in (
                (EXPL, 10.0, 60.0, 6.0, (11.77, 40.34)), (REST, 5.0, 35.0, 6.0, (13.14, 20.83))):
            advance = height / tan_deg(face) + berm
            self.assertAlmostEqual(advance, wanted[0], delta=0.005)
            self.assertAlmostEqual(general_deg(height, face, berm), wanted[1], delta=0.005)
            self.assertEqual(shown[name].derived, f"avance {number(advance, 2)} m · talud general "
                                                  f"{number(general_deg(height, face, berm), 2)}°")
            self.assertEqual(shown[name].summary, f"h {number(height, 0)} m · cara "
                                                  f"{number(face, 0)}° · berma {number(berm, 0)} m "
                                                  f"· ancla 125 m")
        for key, value in ((f"des.bench.{EXPL_CODE}.height_m", 10.0),
                           (f"des.bench.{EXPL_CODE}.face_deg", 60.0),
                           (f"des.bench.{EXPL_CODE}.berm_m", 6.0),
                           (f"des.bench.{EXPL_CODE}.anchor_m", 125.0),
                           (f"des.bench.{REST_CODE}.height_m", 5.0)):
            ((kind, stored),) = self.rows("SELECT kind, value FROM gb_parameter WHERE key = ?", key)
            self.assertEqual((kind, json.loads(stored)), ("ADOPTADO", value), key)

    # --- b: la vista previa --------------------------------------------------------------------

    def pump(self) -> Any:
        """Los pasos de la construcción de la vista previa, uno por llamada del temporizador (en
        ``blender -b`` no corren) hasta que acaba: lo construido."""
        for _ in range(MAX_EVENTS):
            if self.design.tick() is None:
                built = self.design.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def show(self, **values: Any) -> Any:
        """Activa la vista previa con la orden (por defecto, las semillas del fondo del hueco) y la
        construye."""
        form = {"seeds_from": "FIXED", "zone": "sector:sector_1", "elevation": "630", **values}
        self.assertEqual(bpy.ops.geoblender.des_toggle_preview("EXEC_DEFAULT", **form),
                         {"FINISHED"})
        return self.pump()

    def truth(self, seeds: Any, version: Any = None) -> Any:
        """Lo que dice ``design`` de unas semillas (``design.steps.preview_steps``), sin pasar por el
        dibujo."""
        target = self.v01 if version is None else version
        found = None
        for step in self.dsteps.preview_steps(self.project, self.design.Plan(seeds), target.uid):
            found = step.result if step.result is not None else found
        return found

    def test_b_the_preview_counts_the_cells_and_writes_nothing(self) -> None:
        """RF-013-01, RF-013-02, RF-013-03, CE-013-07 (E5; M1): con la orden de la vista previa, las
        semillas del fondo del hueco (el sector 1: 35 × 80 celdas de 2 m a 630 m) son un punto por celda
        en su cota, el dominio de trabajo es de 8.540 celdas (el por defecto, 6.840, y la franja de solo
        relleno, 1.700), el sector 2 se ve pendiente y su aviso lo dice; la ladera entera dice cuántas
        celdas de semilla quedan fuera del dominio (25.600 − 8.540 = 17.060) y las avisa; V02, sin
        máscaras, lo dice y no da semillas. Lo dibujado es lo que dice ``design`` y no escribe nada."""
        files, operations = self.hashes(), self.rows("SELECT count(*) FROM gb_operation")
        number = self.i18n.format_number
        seeds_model = self.dmodel.SeedSource(self.dmodel.SeedKind.FIXED, elevation_m=BOTTOM_M,
                                             zone=self.dmodel.Zone(self.dmodel.ZoneKind.SECTOR,
                                                                   "sector_1"))
        built = self.show()
        self.assertEqual(built.lines.masks, "current")
        self.assertEqual((built.seeds.count, built.seeds.total, built.seeds.stride),
                         (PIT_SEEDS,) * 2 + (1,))
        self.assertEqual((round(built.seeds.low, 6), round(built.seeds.high, 6)), (BOTTOM_M,) * 2)
        self.assertEqual(sorted(built.sectors), [("Sector 1", False), ("Sector 2", True)])
        found = self.truth(seeds_model)
        self.assertEqual((found.seeds.cells, found.seeds.area_m2), (PIT_SEEDS, PIT_SEEDS * 4.0))
        self.assertEqual((found.seeds.min_m, found.seeds.max_m, found.seeds.outside_domain),
                         (BOTTOM_M, BOTTOM_M, 0))
        self.assertEqual(found.domain.cells, DOMAIN_CELLS)
        self.assertEqual([(s.code, s.touched, s.pending) for s in found.sectors],
                         [("sector_1", True, False), ("sector_2", True, True)])
        self.assertEqual(built.summary, tuple((notice.text("es"), notice.severity == "warning")
                                              for notice in found.notices))
        text = " ".join(line for line, _alert in built.summary)
        self.assertIn(f"Semillas: {number(PIT_SEEDS, 0)} celdas ({number(PIT_SEEDS * 4, 0)} m²), "
                      f"cotas 630,0 a 630,0 m", text)
        self.assertIn(f"{number(DOMAIN_CELLS, 0)} celdas ({number(DOMAIN_CELLS * 4, 0)} m²)", text)
        self.assertIn("Sector «Sector 2»: búsqueda de intocables pendiente", text)
        self.design.disable()

        everything = self.show(seeds_from="SURFACE", surface=self.start_name, zone="none")
        outside = CELLS * CELLS - DOMAIN_CELLS
        self.assertEqual(everything.seeds.total, CELLS * CELLS)
        text = " ".join(line for line, _alert in everything.summary)
        self.assertIn(f"{number(outside, 0)} celdas de semilla fuera del dominio", text)
        self.assertIn(f"{number(outside, 0)} celdas de semilla ({number(outside * 4, 0)} m²) están "
                      f"fuera del dominio de trabajo", text)
        self.assertTrue(any(alert for _line, alert in everything.summary))
        self.i18n.set_language("en")
        self.design.rebuild()
        self.assertIn(f"{outside:,} seed cells outside the work domain",
                      " ".join(line for line, _alert in self.pump().summary))
        self.i18n.set_language("es")
        self.design.disable()

        self.set_active(self.v02)
        try:
            missing = self.show()
            self.assertEqual(missing.lines.masks, "missing")
            self.assertIsNone(missing.seeds)
            self.assertTrue(any(alert for _line, alert in missing.summary))
            self.assertIs(self.access.mask_state(self.project, self.v02.uid)[0],
                          self.access.MaskState.MISSING)  # la vista previa no compila
        finally:
            self.design.disable()
            self.set_active(self.v01)
        self.assertEqual((self.hashes(), self.rows("SELECT count(*) FROM gb_operation")),
                         (files, operations), "la vista previa solo lee")

    # --- c: un sector sin búsqueda ---------------------------------------------------------------

    def nothing_left(self, operations: int, files: list[str]) -> None:
        """Una orden que se niega o se cancela no deja operación, dato, cifra ni temporal de la 013."""
        self.assertEqual(self.des_operations(), operations)
        self.assertEqual(self.datasets(), [])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"), [(0,)])
        self.assertEqual(self.names(), files)
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001 - el escalonado que esperaba

    def test_c_a_sector_without_a_search_refuses_the_calculation(self) -> None:
        """RF-013-05, RF-013-06, CE-013-06 (E5; M6): con la búsqueda de intocables del sector 2 sin
        hacer, el cálculo se niega nombrando el sector 2 (no el 1) y la orden de la 012, en los dos
        idiomas, sin dejar nada (ni operación, ni dato, ni temporal); acotado al sector 1, que sí tiene
        su búsqueda, se calcula. Hecha la búsqueda del sector 2, las máscaras quedan obsoletas (la vista
        previa lo dice) y, compiladas de nuevo, la vista previa ve vigentes los dos sectores."""
        operations, files = self.des_operations(), self.names()
        for language, order in (("es", "Buscar elementos intocables por sector…"),
                                ("en", "Find untouchable elements by sector…")):
            with self.subTest(idioma=language):
                self.i18n.set_language(language)
                state, _calls = self.drive(self.start())
                self.assertEqual(state, {"CANCELLED"})
                text = " ".join(self.running_log())
                self.assertIn("Sector 2", text)
                self.assertNotIn("Sector 1", text)
                self.assertIn(order, text)
                self.nothing_left(operations, files)
        self.i18n.set_language("es")
        row = next(item for item in self.view.sectors if item.code == "sector_1")
        row.use = True
        state, _calls, _modal = self.calculate(bound="SECTORS")
        self.assertEqual(state, {"FINISHED"})  # acotado al sector 1, que sí tiene su búsqueda
        self.des_ops.discard_calculation()
        row.use = False
        self.nothing_left(operations, files)
        self.close_search("sector_2", 2)
        self.refresh_lists()
        stale = self.show()  # cerrar una búsqueda deja las máscaras obsoletas: a compilar de nuevo
        self.assertEqual((stale.lines.masks, stale.seeds), ("stale", None))
        self.design.disable()
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        built = self.show()
        self.assertEqual(sorted(built.sectors), [("Sector 1", False), ("Sector 2", False)])
        self.assertEqual(built.lines.masks, "current")
        self.assertFalse(any(alert for _line, alert in built.summary), built.summary)

    def running_log(self) -> list[str]:
        """Lo que dijo la última orden de Diseño que se lanzó con ``start`` (su ``report_log``)."""
        return list(self._last.report_log)

    # --- d: Esc a mitad -------------------------------------------------------------------------

    def test_d_esc_midway_leaves_nothing(self) -> None:
        """RF-013-33, D-14 (M6): Esc a mitad de calcular el hueco con su escalonado, con el temporal ya
        escrito, no deja nada: ni operaciones en curso, ni datos, ni cifras, ni ficheros nuevos, ni
        cálculo abierto ni el escalonado pendiente; la cancelación del modal por Blender, tampoco."""
        cls = self.commands.registered_class(OPEN)
        operations, files = self.des_operations(), self.names()
        form = {"stepped": True, "sense": "CUT", "start": self.start_name, "base_profile": EXPL}
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # un paso por llamada
            for label, how in (("Esc", "esc"), ("Blender cancela", "cancel")):
                with self.subTest(forma=label):
                    modal = self.start(**form)
                    self.drive(modal, until=lambda: bool(self.temporaries()))
                    self.assertTrue(self.temporaries(), "no llegó a escribir el temporal")
                    self.assertEqual(len(self.des_ops._NEXT), 1)  # noqa: SLF001
                    if how == "esc":
                        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                    else:
                        modal.cancel(bpy.context)
                    self.assertIsNone(modal._steps)  # noqa: SLF001
                    self.assertEqual(self.operations(ENVELOPE_TYPE, "running"), [])
                    self.nothing_left(operations, files)

    # --- e: E1, el hueco que sube desde un fondo --------------------------------------------------

    def test_e_the_pit_rises_from_its_bottom_and_is_stepped_in_cut(self) -> None:
        """RF-013-11, RF-013-12, RF-013-17, RF-013-22, RF-013-26, RF-013-31, RF-013-33, D-14, CE-013-01,
        CE-013-03 (E1; M4): el hueco que sube desde un fondo a 630 m en el sector 1, con la pendiente
        general de ``EXPL_10_60_6`` y su escalonado en corte, calculados y creados con la orden:
        «Calcular» da el resumen y deja un temporal sin registrar nada; «Crear» registra la envolvente de
        las 8.540 celdas del dominio, con el fondo a 630 m y, al este, ``630 + k·2·tan·0,98644`` a
        ≤ 10⁻⁹ m; y luego el escalonado: bermas en ``125 + 10·n``, corte por encima de la envolvente
        con menos de un banco, nunca sobre el terreno, el desmonte de las celdas releídas (≤ 10⁻⁹
        relativo), la rejilla de bermas y su tabla, ninguna cara pasa de 60° más la tolerancia. Cada
        llamada del modal dura menos de 0,2 s de CPU."""
        operations, files = self.des_operations(), self.names()
        state, calls, _modal = self.calculate(stepped=True, sense="CUT", start=self.start_name,
                                              base_profile=EXPL)
        self.assertEqual(state, {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.version, held.open),
                         (ENVELOPE_TYPE, "Hueco", "V01", True))
        self.assertEqual((self.des_operations(), self.datasets()), (operations, []))  # D-14
        self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual(len(self.names()), len(files) + 1, "solo el temporal")
        self.assertEqual(self.view.summary_title, "Envolvente «Hueco» en V01")
        number = self.i18n.format_number
        self.assertEqual(self.view.summary[0].name, f"Envolvente «Hueco»: {number(DOMAIN_CELLS, 0)} "
                                                    f"celdas ({number(DOMAIN_CELLS * 4, 0)} m²)")

        self.assertEqual(self.create(), {"RUNNING_MODAL"})  # la envolvente, y sigue el escalonado
        (made,) = self.operations(ENVELOPE_TYPE, "done")
        self.assertEqual(self.datasets(), ["des_env_hueco"])
        self.assertEqual(self.temporaries(), [])
        env = self.grid_of("env", "Hueco")
        self.assertEqual(int(np.isfinite(env).sum()), DOMAIN_CELLS)
        self.assertEqual(float(np.nanmin(env)), BOTTOM_M)
        seeds = np.zeros(env.shape, dtype=bool)
        seeds[row_of(179.0):row_of(21.0) + 1, col_of(21.0):col_of(89.0) + 1] = True
        self.assertEqual(int(seeds.sum()), PIT_SEEDS)
        self.assertTrue(np.all(env[seeds] == BOTTOM_M))
        tan = tan_deg(EXPL_GENERAL_DEG)
        for y in (60.0, 101.0, 139.0):
            row = row_of(y)
            for k in range(1, 41):
                self.assertAlmostEqual(env[row, col_of(89.0) + k],
                                       BOTTOM_M + k * STEP_M * tan * SCALE, delta=1e-9,
                                       msg=f"fila y={y}, {k} celdas al este del fondo")
        figures = self.figures_of(made[0])
        self.assertEqual((figures["des.env_cells"], figures["des.env_min_m"]), (DOMAIN_CELLS, BOTTOM_M))
        self.assertAlmostEqual(figures["des.env_max_m"], float(np.nanmax(env)), delta=1e-9)
        self.assertNotIn("des.env_cut_m3", figures, "unas semillas de cota fija no tienen partida")

        state, more = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        calls += more
        self.assertLess(max(calls), 0.2)  # RNF-013-07, sin la transacción final de «Crear»
        self.assertEqual(self.view.summary_title, "Escalonado «Hueco» en V01")
        self.assertEqual(self.operations(STEPPED_TYPE), [])  # el escalonado, aún sin registrar
        started = time.process_time()
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertLess(time.process_time() - started, 0.2)  # también la transacción final (31 ms)
        stepped = self.last_done(STEPPED_TYPE, "Hueco")
        self.assertEqual(self.datasets(), ["des_bmt_hueco", "des_brm_hueco", "des_env_hueco",
                                           "des_rpt_hueco", "des_srf_hueco"])
        design, brm = self.grid_of("srf", "Hueco"), self.grid_of("brm", "Hueco")
        start = self.start_values()
        self.assertFalse(np.isnan(design).any(), "la superficie de diseño no tiene huecos")
        self.assertTrue(np.all(design <= start), "el corte nunca sube el terreno")
        moved = start - design > 0.02
        self.assertGreater(int(moved.sum()), 2000)
        self.assertTrue(np.array_equal(moved & np.isfinite(env), moved), "solo donde hay envolvente")
        gap = design[moved] - env[moved]
        self.assertGreaterEqual(float(gap.min()), -1e-9, "el corte queda por encima de S")
        self.assertLess(float(gap.max()), 10.0 + 1e-9, "con menos de un banco de diferencia")
        figures = self.figures_of(stepped)
        cut = self.moved_volume(start, design, 1.0)
        self.assertAlmostEqual(figures["des.cut_m3"] / cut, 1.0, delta=1e-9)
        self.assertEqual(figures["des.fill_m3"], 0.0)
        self.assertGreater(cut, 100_000.0)
        finite = np.isfinite(brm)
        levels = (brm[finite] - PROFILE_ANCHOR) / 10.0
        self.assertLessEqual(float(np.abs(levels - np.round(levels)).max()) * 10.0, 1e-9,
                             "las bermas están en 125 + 10·n")
        self.assertTrue(np.array_equal(design[finite], brm[finite]))
        rows = self.berm_rows("Hueco")
        self.assertEqual(len(rows), figures["des.berm_count"])
        self.assertEqual(sum(row[3] for row in rows), int(finite.sum()))
        for _sector, profile, level, cells, area, _anchor, diff in rows:
            self.assertEqual(profile, EXPL_CODE)
            self.assertAlmostEqual((level - PROFILE_ANCHOR) / 10.0,
                                   round((level - PROFILE_ANCHOR) / 10.0), delta=1e-9)
            self.assertEqual(area, cells * self.area)
            self.assertLessEqual(abs(diff), 1e-6)
        inside = self.compose.allowed_cells(self.masks(), "cut") & np.isfinite(env)
        worst = incline_pairs(design, inside)
        self.assertLessEqual(worst, 60.0 + TOLERANCE_FACE_DEG)
        self.assertGreater(worst, 45.0, "la prueba mira las caras de verdad")
        codes = self.report_codes("Hueco")
        self.assertIn("des.magnitude_no_reference", codes, "la primera vez no hay revisión con que comparar")
        self.assertIn("des.slope_over_face", codes)
        self.assertAlmostEqual(figures["des.slope_max_deg"], moved_incline(design, moved), delta=1e-9)
        self.assertGreater(figures["des.slope_max_deg"], 80.0,
                           "contra lo prohibido (la cuneta) hay un escalón, y el informe lo dice")
        self.assertGreater(figures["des.edge_step_max_m"], 10.0)

    # --- f: E2, el hueco que baja desde el límite legal ---------------------------------------------

    def test_f_the_exact_envelope_from_the_legal_limit_is_the_hand_distance(self) -> None:
        """RF-013-01, RF-013-12, RF-013-14, CE-013-01 (E2): las semillas son el terreno (650 m) en el
        borde interior del límite legal (1.900 celdas: la banda de 10 m, como una capa de polígonos) y
        la envolvente descendente euclídea exacta vale, en cada celda, ``650 − tan 35°·d`` con ``d`` la
        distancia mínima entre centros de celda a las semillas (fuerza bruta, ≤ 10⁻⁹ relativo); el
        desmonte frente al terreno es el de las celdas; y el *chamfer* de la ascendente del hueco
        difiere de la exacta ≤ 1,4 % (RF-013-12)."""
        self.write_layer("gis_fea_borde", [rectangle(0.0, 0.0, 200.0, 200.0),
                                           rectangle(10.0, 10.0, 190.0, 190.0)[::-1]])
        state, _calls, _modal = self.calculate(
            name="Hueco bajo el limite", seeds_from="SURFACE", surface=self.start_name,
            zone="layer:gis_fea_borde", direction="DOWN", metric="EXACT", slope="35")
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.des_ops.calculation().seeds.cells, 1900)
        self.assertEqual(self.create(), {"FINISHED"})
        env = self.grid_of("env", "Hueco bajo el limite")
        band = self.masks().zone(f"{self.codes['legal_limit']}:inner").mask(env.shape)
        self.assertEqual(int(band.sum()), 1900)
        self.assertTrue(np.all(env[band & np.isfinite(env)] == START_Z), "las semillas son el terreno")
        rows, cols = np.nonzero(np.isfinite(env))
        seed_rows, seed_cols = np.nonzero(band)
        self.assertEqual(rows.size, DOMAIN_CELLS)
        worst = 0.0
        for first in range(0, rows.size, 1000):  # fuerza bruta en todas las celdas, por trozos
            chunk = slice(first, first + 1000)
            distance = np.hypot(rows[chunk, None] - seed_rows[None, :],
                                cols[chunk, None] - seed_cols[None, :]).min(axis=1) * STEP_M
            measured = (START_Z - env[rows[chunk], cols[chunk]]) / tan_deg(35.0)
            worst = max(worst, float(np.abs(measured - distance).max()))
            self.assertGreater(float(distance.max()), 0.0)
        self.assertLessEqual(worst, 1e-9 * 100.0, "d a 10⁻⁹ relativo de los 100 m más lejanos")
        made = self.last_done(ENVELOPE_TYPE, "Hueco bajo el limite")
        figures = self.figures_of(made)
        finite = np.isfinite(env)
        self.assertAlmostEqual(
            figures["des.env_cut_m3"] / float(np.sum(np.clip(self.start_values()[finite] - env[finite],
                                                             0.0, None)) * self.area), 1.0, delta=1e-9)
        self.assertEqual(figures["des.env_fill_m3"], 0.0)

        # El mismo hueco con la métrica exacta (sin crearlo): el chamfer difiere ≤ 1,4 % (RF-013-12).
        state, _calls, _modal = self.calculate(name="Hueco exacto", metric="EXACT")
        self.assertEqual(state, {"FINISHED"})
        exact = self.des_ops.calculation().outcome
        chamfer = self.grid_of("env", "Hueco")
        rise_c = (chamfer - BOTTOM_M) / tan_deg(EXPL_GENERAL_DEG)
        rise_e = (exact.grid - BOTTOM_M) / tan_deg(EXPL_GENERAL_DEG)
        far = np.isfinite(rise_e) & (rise_e > 0.0)
        self.assertTrue(far.any())
        self.assertLessEqual(float(np.abs(rise_c[far] / rise_e[far] - 1.0).max()), 0.014)
        self.assertGreater(float(np.abs(rise_c[far] / rise_e[far] - 1.0).max()), 0.005,
                           "las dos métricas no son la misma")
        self.assertIsNotNone(exact.envelope.reduction)
        self.des_ops.discard_calculation()
        self.assertEqual(self.temporaries(), [])

    # --- g: E3, el relleno de berma primero ----------------------------------------------------------

    def test_g_the_mound_is_filled_berm_first_with_rest_5_35_6(self) -> None:
        """RF-013-01, RF-013-02, RF-013-14, RF-013-23, CE-013-03 (E3; M5): las semillas son las 25
        celdas de una capa de polígonos a 660 m en una superficie, el dominio se acota a otra capa y la
        envolvente descendente tiene como mucho 40 m de alcance; el relleno de berma primero con
        ``REST_5_35_6`` queda por debajo de la envolvente con menos de un banco de diferencia, por
        encima del terreno, con las bermas en ``125 + 5·n`` y el terraplén de las celdas."""
        top = self.write_grid("montera", np.full((CELLS, CELLS), MOUND_TOP_M))
        self.write_layer("gis_fea_montera", [rectangle(144.0, 56.0, 154.0, 66.0)])
        self.write_layer("gis_fea_ambito", [rectangle(100.0, 20.0, 190.0, 100.0)])
        state, _calls, _modal = self.calculate(
            stepped=True, name="Montera", seeds_from="SURFACE", surface=top,
            zone="layer:gis_fea_montera", direction="DOWN", metric="CHAMFER5",
            slope=repr(REST_GENERAL_DEG), reach="40", bound="LAYER", bound_layer="gis_fea_ambito",
            sense="FILL", start=self.start_name, base_profile=REST)
        self.assertEqual(state, {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual((held.seeds.cells, held.seeds.outside_domain), (25, 0))
        self.assertEqual(self.create(), {"RUNNING_MODAL"})
        env = self.grid_of("env", "Montera")
        tan = tan_deg(REST_GENERAL_DEG)
        row, last_seed = row_of(61.0), col_of(153.0)
        for k in range(1, 18):  # hasta x = 187 m: la capa del dominio acaba en 190 m
            self.assertAlmostEqual(env[row, last_seed + k], MOUND_TOP_M - k * STEP_M * tan * SCALE,
                                   delta=1e-9)
        self.assertGreater(int(np.isfinite(env).sum()), 400)
        self.assertEqual(float(np.nanmax(env)), MOUND_TOP_M)
        layer = np.zeros(env.shape, dtype=bool)  # la capa del dominio: de 100 a 190 m y de 20 a 100 m
        layer[row_of(99.0):row_of(21.0) + 1, col_of(101.0):col_of(189.0) + 1] = True
        self.assertFalse((np.isfinite(env) & ~layer).any(), "el dominio, acotado a la capa")
        self.assertTrue(np.isfinite(env[row_of(99.0), col_of(151.0)]), "a 33 m, dentro de la capa")
        self.assertTrue(np.isnan(env[row_of(103.0), col_of(151.0)]), "a 37 m, pero fuera de la capa")
        state, calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual(self.create(), {"FINISHED"})
        design, brm = self.grid_of("srf", "Montera"), self.grid_of("brm", "Montera")
        start = self.start_values()
        self.assertTrue(np.all(design >= start), "el relleno nunca baja el terreno")
        moved = design - start > 0.02
        self.assertGreater(int(moved.sum()), 100)
        under = env[moved] - design[moved]
        self.assertGreaterEqual(float(under.min()), -1e-9, "el relleno queda por debajo de S")
        self.assertLess(float(under.max()), 5.0 + 1e-9, "con menos de un banco de diferencia")
        figures = self.figures_of(self.last_done(STEPPED_TYPE, "Montera"))
        fill = self.moved_volume(start, design, -1.0)
        self.assertAlmostEqual(figures["des.fill_m3"] / fill, 1.0, delta=1e-9)
        self.assertEqual(figures["des.cut_m3"], 0.0)
        finite = np.isfinite(brm)
        self.assertTrue(finite.any())
        levels = (brm[finite] - PROFILE_ANCHOR) / 5.0
        self.assertLessEqual(float(np.abs(levels - np.round(levels)).max()) * 5.0, 1e-9)
        inside = self.compose.allowed_cells(self.masks(), "fill") & np.isfinite(env)
        self.assertLessEqual(incline_pairs(design, inside), 35.0 + TOLERANCE_FACE_DEG)
        self.assertEqual(figures["des.berm_count"], len(self.berm_rows("Montera")))

    # --- h: E4, el frente tendido de un sector (V02) --------------------------------------------------

    def dataset_hashes(self) -> dict[str, str]:
        """El hash de contenido de cada dato de ``des`` y su estado, en todo el proyecto."""
        return {name: f"{status}:{sha}" for name, status, sha in self.rows(
            "SELECT name, status, content_sha256 FROM gb_dataset WHERE name LIKE 'des!_%' "
            "ESCAPE '!' AND status = 'current' ORDER BY name")}

    def test_h_the_sector_with_a_general_slope_of_10_6_degrees_has_its_own_berm(self) -> None:
        """RF-013-04, RF-013-09, RF-013-13, RF-013-25, RF-013-26, CE-013-04, CE-013-05 (E4, V02; M3 y
        M5): con el talud general máximo de 10,6° en el sector 2 (ADOPTADO, solo en V02, puesto con la
        orden: V01 no cambia) y las semillas de una capa en el hueco entre los dos sectores, «Calcular»
        compila antes las máscaras de V02 por pasos; la pendiente de la envolvente es la del sector en
        cada celda (``2·tan·0,98644`` entre vecinas, a ≤ 10⁻⁹ m); la berma impuesta es 19,5765237 m (a
        mano, ≤ 10⁻⁹ relativo) y las anchuras medidas en la rejilla coinciden con ella dentro de una
        celda en el sector 2 y con los 6 m del perfil en el sector 1; ninguna inclinación entre celdas
        pasa de la cara más la tolerancia, también entre sectores."""
        sectors = _module("design.sectors")
        benching = _module("design.benching")
        profile = SimpleNamespace(height_m=5.0, face_deg=35.0, berm_m=6.0)
        self.assertAlmostEqual(benching.sector_berm(profile, SECTOR_SLOPE_DEG) / IMPOSED_BERM_M, 1.0,
                               delta=1e-9)
        self.assertAlmostEqual(IMPOSED_BERM_M, 19.5765237, delta=5e-8)
        self.assertEqual(benching.sector_berm(profile, None), 6.0)
        before, stale_before = self.dataset_hashes(), self.rows("SELECT count(*) FROM gb_stale")
        self.set_active(self.v02)
        self.refresh_lists()
        self.assertEqual(bpy.ops.geoblender.des_set_sector_slope(
            code="sector_2", slope="10.6", kind="ADOPTADO", source=SOURCE, source_kind="PERSON",
            decided_by=PERSON, reason="Decisión de la propiedad", scope="VERSION"), {"FINISHED"})
        self.refresh_lists()
        slopes = {version.code: {item.code: item.slope for item in
                                 sectors.design_sectors(self.project, version.uid)}
                  for version in (self.v01, self.v02)}
        self.assertIsNone(slopes["V01"]["sector_2"], "el talud es solo de V02")
        self.assertEqual(slopes["V02"]["sector_2"].value, SECTOR_SLOPE_DEG)
        self.assertIsNone(slopes["V02"]["sector_1"])
        row = next(item for item in self.view.sectors if item.code == "sector_2")
        self.assertEqual(row.slope, "10,6° [ADO]")
        self.write_layer("gis_fea_fondo", [rectangle(92.0, 22.0, 108.0, 178.0)])
        self.assertIs(self.access.mask_state(self.project, self.v02.uid)[0],
                      self.access.MaskState.MISSING)
        state, calls, _modal = self.calculate(
            name="Frente tendido", seeds_from="FIXED", zone="layer:gis_fea_fondo", direction="UP",
            slope_mode="SECTORS", slope="", stepped=True, sense="CUT", start=self.start_name,
            base_profile=REST)
        self.assertEqual(state, {"FINISHED"})
        self.assertIs(self.access.mask_state(self.project, self.v02.uid)[0],
                      self.access.MaskState.CURRENT)  # compiladas antes por pasos
        self.assertEqual(self.des_ops.calculation().seeds.cells, 8 * 78)
        self.assertEqual(self.create(), {"RUNNING_MODAL"})
        env = self.grid_of("env", "Frente tendido", self.v02)
        tan_rest, tan_front = tan_deg(REST_GENERAL_DEG), tan_deg(SECTOR_SLOPE_DEG)
        for y in (61.0, 101.0, 139.0):
            line = env[row_of(y)]
            for c in range(col_of(113.0), col_of(175.0)):  # el sector 2: de 110 a 180 m
                self.assertAlmostEqual(line[c + 1] - line[c], STEP_M * tan_front * SCALE, delta=1e-9)
            for c in range(col_of(25.0), col_of(89.0)):  # el sector 1: de 20 a 90 m
                self.assertAlmostEqual(line[c] - line[c + 1], STEP_M * tan_rest * SCALE, delta=1e-9)
        state, more = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls + more), 0.2)
        self.assertEqual(self.create(), {"FINISHED"})
        design = self.grid_of("srf", "Frente tendido", self.v02)
        self.assertTrue(np.all(design <= self.start_values()))
        wide: list[int] = []
        narrow: list[int] = []
        for y in (61.0, 101.0, 139.0):
            line = design[row_of(y)]
            wide += plateaus(line, PROFILE_ANCHOR, 5.0, col_of(113.0), col_of(175.0))
            narrow += plateaus(line, PROFILE_ANCHOR, 5.0, col_of(23.0), col_of(87.0))
        self.assertGreaterEqual(len(wide), 3, wide)
        self.assertGreaterEqual(len(narrow), 3, narrow)
        for width in wide:
            self.assertLessEqual(abs(width * STEP_M - IMPOSED_BERM_M), STEP_M, wide)
        for width in narrow:
            self.assertLessEqual(abs(width * STEP_M - 6.0), STEP_M, narrow)
        inside = self.compose.allowed_cells(self.masks(self.v02), "cut") & np.isfinite(env)
        worst = incline_pairs(design, inside)
        self.assertLessEqual(worst, 35.0 + TOLERANCE_FACE_DEG)
        self.assertGreater(worst, 25.0, "la prueba mira las caras de verdad")
        self.assertTrue(set(before.items()) <= set(self.dataset_hashes().items()), "V01 no cambió")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_stale"), stale_before)
        self.set_active(self.v01)
        self.refresh_lists()
        row = next(item for item in self.view.sectors if item.code == "sector_2")
        self.assertEqual(row.slope, "")  # en V01, sin talud impuesto

    # --- i: congelar con superficies de diseño sin verificar ---------------------------------------------

    def revisions(self, version: Any = None) -> list[tuple[str, str, str]]:
        """Las revisiones de ``version`` (por defecto V01): (etiqueta, estado, uid)."""
        target = self.v01 if version is None else version
        read = _module("core.versions.read")
        with self.project.read() as conn:
            return [(item.label(target.code), str(item.state), str(item.uid))
                    for item in read.revisions(conn, target.uid)]

    def frozen(self, revision_uid: str) -> dict[str, Any]:
        """Lo congelado por ``revision_uid``: la fila de la revisión y cada elemento."""
        return {
            "revision": self.rows("SELECT state, snapshot_dir, snapshot_sha256, altered_at FROM "
                                  "gb_revision WHERE uid = ?", revision_uid),
            "items": self.rows("SELECT item_kind, item_uid, part, item_rev, content_sha256, copied, "
                               "snapshot_path, snapshot_layer, file_sha256, file_size, state FROM "
                               "gb_revision_item WHERE revision_uid = ? ORDER BY item_kind, "
                               "item_uid", revision_uid)}

    def test_i_freezing_lists_the_unverified_design_surfaces_and_asks_to_accept(self) -> None:
        """CE-013-08, RF-013-31, RF-012-25 (E6; T18): congelar V01.r1 con las superficies de diseño del
        hueco y de la montera sin ninguna verificación al día las lista como hallazgo («es una
        superficie de diseño sin verificación al día»), no congela sin aceptarlas (y no cambia nada) y
        aceptadas deja V01.r1 congelada con las cifras de las cuatro operaciones de V01 y V01.r2
        abierta."""
        dialog = self.versions_ops.revision_dialog(self.project, self.v01.uid)
        shown = " ".join(dialog.accept_lines())
        self.assertEqual(sorted(item.name for item in dialog.accept),
                         ["des_srf_hueco", "des_srf_montera"], shown)
        self.assertEqual(shown.count("es una superficie de diseño sin verificación al día"), 2, shown)
        self.assertIn("hallazgo", dialog.accept_text())
        before = (self.revisions(), self.hashes())
        with self.assertRaises(RuntimeError):  # sin aceptar, no congela
            bpy.ops.geoblender.core_new_revision("EXEC_DEFAULT", reason="Entrega")
        self.assertEqual((self.revisions(), self.hashes()), before)
        type(self).frozen_ops = {
            (op_type, name): self.last_done(op_type, name)
            for op_type, name in ((ENVELOPE_TYPE, "Hueco"), (STEPPED_TYPE, "Hueco"),
                                  (ENVELOPE_TYPE, "Hueco bajo el limite"),
                                  (ENVELOPE_TYPE, "Montera"), (STEPPED_TYPE, "Montera"))}
        type(self).frozen_figures = {uid: self.figures_of(uid) for uid in self.frozen_ops.values()}
        self.assertEqual(bpy.ops.geoblender.core_new_revision(
            "EXEC_DEFAULT", reason="Entrega", accept=dialog.accepted, in_steps=True),
            {"RUNNING_MODAL"})
        state, calls = self.drive(self.running("geoblender.core_new_revision"))
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual([(label, state) for label, state, _uid in self.revisions()],
                         [("V01.r1", "frozen"), ("V01.r2", "open")])
        type(self).r1 = self.revisions()[0][2]
        read = _module("core.versions.read")
        with self.project.read() as conn:
            kept = {}
            for item in read.version_figures(conn, self.v01.uid):
                kept[item.key] = kept.get(item.key, 0) + 1
        self.assertEqual((kept["des.env_cells"], kept["des.cut_m3"], kept["des.fill_m3"]), (3, 2, 2),
                         "V01.r1 congela las cifras de las 3 envolventes y los 2 escalonados")
        self.assertTrue(self.frozen(self.r1)["items"])

    # --- j: recalcular lo obsoleto y reproducir ----------------------------------------------------------

    def stale(self) -> dict[str, Any]:
        """Las operaciones obsoletas sin sustituir con sus causas (``deduce`` de la 008)."""
        with self.project.read() as conn:
            return dict(self.graph.deduce(self.graph.load_graph(conn)).operations)

    def settings_of(self, uid: str) -> dict[str, Any]:
        return dict(json.loads(self.rows("SELECT settings FROM gb_operation WHERE uid = ?",
                                         uid)[0][0]))

    def test_j_recomputing_what_became_stale_and_reproducing_the_frozen(self) -> None:
        """CE-013-08, RF-013-17, RF-013-30, RF-013-31, RF-008-26, RF-009-11, D-25 (E6; M7): cambiar el
        ancla de ``EXPL_10_60_6`` solo en V01 deja obsoleto solo el escalonado de corte del hueco (el
        resto no lee ese ancla) y «Recalcular lo obsoleto» lo repite sin pedir confirmación y por la
        cola, en la revisión abierta: sus bermas están en ``127 + 10·n``, su desmonte cambia y se
        compara con el de V01.r1; la envolvente y lo demás no se tocan, y lo congelado tampoco.
        Reproducir V01.r1 da, sin escribir en el proyecto, las mismas salidas con el mismo hash y las
        mismas cifras que lo congelado."""
        self.maxDiff = None
        design = self.frozen_ops[(STEPPED_TYPE, "Hueco")]
        frozen, before = self.frozen(self.r1), self.dataset_hashes()
        self.assertEqual(self.stale(), {})
        key = f"des.bench.{EXPL_CODE}.anchor_m"
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value=repr(NEW_ANCHOR_M), kind="ADOPTADO", source=SOURCE, source_kind="DOCUMENT",
            decided_by=PERSON, reason=REASON, scope="VERSION"), {"FINISHED"})
        ((own,),) = self.rows("SELECT uid FROM gb_parameter WHERE key = ? AND scope_uid = ?", key,
                              self.v01.uid)
        found = self.stale()
        self.assertEqual(sorted(found), [design], "solo el escalonado de corte del hueco lee el ancla")
        self.assertEqual(found[design],
                         {self.graph.Cause(self.graph.CauseKind.PARAMETER_CHANGED, own)})
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text") as status:
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"),
                             {"RUNNING_MODAL"})
            operator = self.running(RECOMPUTE)
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
            calls: list[float] = []
            for _ in range(MAX_EVENTS):
                started = time.process_time()
                state = operator.modal(bpy.context, TIMER)
                self.des_ops.des_tick()  # el temporizador de la cola (en blender -b, a mano)
                calls.append(time.process_time() - started)
                if state != {"RUNNING_MODAL"}:
                    break
            else:
                self.fail("el recálculo no acaba")
        ask.assert_not_called()  # sin pedir confirmación
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.4)  # una llamada del modal y un paso de la cola
        self.assertEqual({str(result.status) for result in operator.result.results}, {"done"})
        self.assertIn("Recalculando «Hueco»… 100 %", [call.args[0] for call in status.call_args_list])
        self.assertEqual((self.des_ops.pending_runs(), self.stale(), self.temporaries()), ([], {}, []))
        self.assertIsNone(self.des_ops.calculation())
        new = self.last_done(STEPPED_TYPE, "Hueco")
        self.assertNotEqual(new, design)
        ((opened,),) = self.rows("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = "
                                 "'open'", self.v01.uid)
        self.assertEqual(self.rows("SELECT op_type, status, revision_uid, supersedes_uid FROM "
                                   "gb_operation WHERE uid = ?", new),
                         [(STEPPED_TYPE, "done", opened, design)])
        after = self.dataset_hashes()
        changed = sorted(name for name in after if after[name] != before.get(name))
        self.assertIn("des_srf_hueco", changed)
        self.assertTrue(set(changed) <= {"des_srf_hueco", "des_brm_hueco", "des_bmt_hueco",
                                         "des_rpt_hueco"}, changed)
        for name in ("des_env_hueco", "des_env_hueco_bajo_el_limite", "des_env_montera",
                     "des_srf_montera"):
            self.assertEqual(after[name], before[name], name)
        rows = self.berm_rows("Hueco")
        self.assertTrue(rows)
        for _sector, _profile, level, *_rest in rows:
            self.assertAlmostEqual((level - NEW_ANCHOR_M) / 10.0,
                                   round((level - NEW_ANCHOR_M) / 10.0), delta=1e-9)
        self.assertNotIn("des.magnitude_no_reference", self.report_codes("Hueco"),
                         "se comparó con el escalonado de V01.r1")
        old, figures = self.frozen_figures[design], self.figures_of(new)
        self.assertNotEqual(figures["des.cut_m3"], old["des.cut_m3"])
        self.assertEqual(self.dprov.settings_previous(self.settings_of(new)), {
            "operation": "Hueco", "revision": "V01.r1", "cut_m3": old["des.cut_m3"],
            "fill_m3": old["des.fill_m3"]})
        self.assertEqual(self.frozen(self.r1), frozen, "lo congelado no cambia")
        findings = self.graph.drain(_module("core.versions.check").check_steps(
            self.project, [self.r1], full=True))
        self.assertEqual([item.altered for item in findings], [False])

        # Reproducir V01.r1 con otra ancla viva: las mismas salidas, bit a bit, sin escribir.
        outside = {name: sha for name, sha in self.hashes().items() if Path(name).parts[0] != "cache"}
        with mock.patch.object(self.versions_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.core_reproduce_version("EXEC_DEFAULT",
                                                                       in_steps=True),
                             {"RUNNING_MODAL"})
            state, calls = self.drive(self.running(REPRODUCE))
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual({name: sha for name, sha in self.hashes().items()
                          if Path(name).parts[0] != "cache"}, outside, "reproducir no escribe")
        (folder,) = (path for path in (self.project.cache_dir() / "reproducir").iterdir()
                     if path.name.startswith("V01.r1-"))
        report = json.loads((folder / "informe.json").read_text(encoding="utf-8"))
        self.assertEqual((report["revision"], report["matches"], report["not_reproducible"]),
                         ("V01.r1", True, []))
        roles: dict[str, list[str]] = {}
        for check in report["outputs"]:
            self.assertTrue(check["same"], check)
            self.assertEqual(check["reproduced_sha256"], check["frozen_sha256"])
            roles.setdefault(check["operation_uid"], []).append(check["role"])
        compiled = {uid: sorted(found) for uid, found in roles.items()
                    if uid not in self.frozen_ops.values()}
        self.assertEqual(list(compiled.values()), [["classes", "parts", "report", "shapes", "zones"]],
                         "además de las cinco operaciones de des, la compilación de las máscaras")
        self.assertEqual({uid: sorted(found) for uid, found in roles.items() if uid not in compiled}, {
            uid: ["envelope"] if op_type == ENVELOPE_TYPE else
            ["berm_table", "berms", "design_surface", "report"]
            for (op_type, _name), uid in self.frozen_ops.items()})
        reproduced = {}
        for check in report["figures"]:
            self.assertTrue(check["same"], check)
            reproduced.setdefault(check["operation_uid"], {})[check["key"]] = check["reproduced"]
        self.assertEqual({uid: found for uid, found in reproduced.items() if uid in self.frozen_figures},
                         self.frozen_figures)
        self.assertEqual(set(reproduced) - set(self.frozen_figures), set(compiled),
                         "y las cifras de la compilación de las máscaras, que también coinciden")

    # --- k: exportar -----------------------------------------------------------------------------------

    def test_k_export_the_grids_to_geotiff_without_writing_in_the_project(self) -> None:
        """RF-013-34, RF-006-24 (M7): «Exportar rejilla a GeoTIFF…» escribe por pasos la envolvente, la
        superficie de diseño y la rejilla de cotas de berma del hueco como GeoTIFF entregable —las
        cotas registradas en float32, el «sin dato» −9999 y el CRS del proyecto—, ninguna llamada de
        más de 0,2 s, sin cambiar ni una operación, un dato, un evento o un fichero del proyecto; un
        fichero que ya existe se rechaza."""
        out = Path(tempfile.mkdtemp(prefix="gb-h2-exp-"))
        self.addCleanup(remove_tree, out)
        counts = [self.rows(f"SELECT count(*) FROM {table}")[0]
                  for table in ("gb_operation", "gb_dataset", "gb_event")]
        files = self.names()
        for family in ("env", "srf", "brm"):
            with self.subTest(grid=family):
                name = self.dprov.dataset_name(family, "Hueco")
                uid = self.dataset_uid(family, "Hueco")
                target = out / f"{name}.tif"
                self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                    "EXEC_DEFAULT", source=uid, filepath=str(target), in_steps=True),
                    {"RUNNING_MODAL"})
                state, calls = self.drive(self.running(EXPORT))
                self.assertEqual(state, {"FINISHED"})
                self.assertLess(max(calls), 0.2)
                ((locator,),) = self.rows("SELECT locator FROM gb_dataset WHERE uid = ?", uid)
                stored = self.reader.read_geotiff(self.root.joinpath(*locator.split("/")),
                                                  max_cells=10 ** 7)
                found = self.reader.read_geotiff(target, max_cells=10 ** 7)
                self.assertEqual(found.grid, stored.grid)
                self.assertEqual((found.declared_crs.epsg, found.source_dtype, found.nodata_value),
                                 (self.project.record.crs_epsg, "float32", -9999.0))
                self.assertTrue(np.isfinite(found.values).any(), name)
                np.testing.assert_array_equal(  # 0 m: lo registrado en float32 (NaN con NaN)
                    found.values, stored.values.astype(np.float32).astype(np.float64))
        with self.assertRaises(RuntimeError) as raised:  # sobre un fichero que existe
            bpy.ops.geoblender.des_export_design_grid(
                "EXEC_DEFAULT", source=self.dataset_uid("srf", "Hueco"),
                filepath=str(out / "des_srf_hueco.tif"))
        self.assertIn("Ya existe «des_srf_hueco.tif»", str(raised.exception))
        self.assertEqual([self.rows(f"SELECT count(*) FROM {table}")[0]
                          for table in ("gb_operation", "gb_dataset", "gb_event")], counts)
        self.assertEqual(self.names(), files)

    # --- l: «Verificar un diseño por recinto…» -------------------------------------------------------------

    def check_table(self, name: str, version: Any) -> dict[tuple[str, int, str], Any]:
        """La tabla ``res_chk_`` de la verificación ``name``: (zona, final, cantidad) → (valor, nota)."""
        store = _module("reserves.compliance_store")
        locator = store.dataset_locator(store.TABLE, name, version.code)
        return {(zone, final, quantity): (value, note) for zone, final, quantity, value, note in
                self.rows(f'SELECT zone, "final", quantity, value, note FROM "{locator}"')}

    def verify(self, version: Any, name: str, finals: tuple[str, ...]) -> dict[tuple[str, int, str], Any]:
        """«Verificar un diseño por recinto…» (012) de las superficies ``finals`` frente a la de
        partida, con la orden y por pasos: la tabla de la verificación."""
        self.set_active(version)
        with mock.patch.object(_module("bl.ops.res"), "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.res_verify_constraints(
                "EXEC_DEFAULT", name=name, start=self.start_name, finals=",".join(finals),
                in_steps=True), {"RUNNING_MODAL"})
            state, calls = self.drive(self.running(VERIFY))
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        return self.check_table(name, version)

    def test_l_the_design_surfaces_verify_zero_cubic_metres_in_every_zone(self) -> None:
        """CE-013-06, RF-013-29, RF-012-21 (E4; M5): «Verificar un diseño por recinto…» de las
        superficies de diseño de V01 (el hueco, ya recalculado, y el relleno de la montera) y de V02 (el
        frente tendido) da 0 m³ en todos los recintos que lo juzgan y cumple; mover una sola celda de
        la torre 1 m, en una copia de la del hueco, hace que falle ese recinto y solo él."""
        for version, names in ((self.v01, ("Hueco", "Montera")), (self.v02, ("Frente tendido",))):
            finals = tuple(self.dprov.dataset_name("srf", name) for name in names)
            table = self.verify(version, f"Revisión {version.code}", finals)
            for position in range(1, len(finals) + 1):
                judged = sorted(zone for (zone, found, quantity), (_value, note) in table.items()
                                if found == position and quantity == "counted_m3"
                                and note in ("cut", "fill", "any"))
                self.assertTrue(judged)
                for zone in judged:
                    self.assertEqual(table[(zone, position, "counted_m3")][0], 0.0, zone)
                    self.assertEqual(table[(zone, position, "verdict")][1], "complies", zone)
                moved = sum(table[key][0] for key in table
                            if key[1] == position and key[2] in ("cut_m3", "fill_m3"))
                self.assertGreater(moved, 10_000.0, "la prueba mueve tierra de verdad")
        self.set_active(self.v01)
        design = self.grid_of("srf", "Hueco").copy()
        tower = np.argwhere(self.masks().zone(self.codes["untouchable"]).mask(design.shape))
        row, col = (int(value) for value in tower[len(tower) // 2])
        design[row, col] -= 1.0
        touched = self.write_grid("tocada", design)
        table = self.verify(self.v01, "Revisión con una celda movida", (touched,))
        failing = sorted(zone for (zone, found, quantity), (_value, note) in table.items()
                         if quantity == "verdict" and note == "fails")
        self.assertEqual(failing, [self.codes["untouchable"]])
        self.assertEqual(table[(self.codes["untouchable"], 1, "counted_m3")][0], self.area)

    # --- m: al cambiar una restricción ---------------------------------------------------------------------

    def test_m_changing_a_restriction_leaves_the_results_stale_with_their_cause(self) -> None:
        """CE-013-06, RF-013-04, RF-013-17 (E6): al cambiar una restricción (la 012), las máscaras
        quedan obsoletas y también, con su causa, las operaciones que las usaron y las superficies que
        escribieron, en las dos versiones; unas máscaras obsoletas no se usan y lo congelado no cambia."""
        stale_module = _module("core.provenance.stale")
        mine = [uid for op_type in (ENVELOPE_TYPE, STEPPED_TYPE)
                for uid, status, superseded in self.operations(op_type)
                if status == "done" and superseded is None]
        self.assertEqual(len(mine), 5 + 2, "V01: 3 envolventes y 2 escalonados; V02: 1 y 1")
        self.assertEqual(self.stale(), {})
        with self.project.read() as conn:
            rows = self.cstore.read_constraints(conn)
        frozen = self.frozen(self.r1)
        self.cprov.edit_constraints(
            self.project, [dataclasses.replace(rows[0], name=rows[0].name + " (editada)")],
            srs_id=self.project.record.crs_epsg)
        for version in (self.v01, self.v02):
            self.assertIs(self.access.mask_state(self.project, version.uid)[0],
                          self.access.MaskState.STALE)
        found = self.stale()
        self.assertTrue(set(mine) <= set(found), set(mine) - set(found))
        self.assertTrue(all(found[uid] for uid in mine), "cada una con su causa")
        with self.project.read() as conn:
            self.assertTrue(stale_module.item_causes(conn, "dataset", self.dataset_uid("srf", "Hueco")))
        self.assertEqual(self.frozen(self.r1), frozen, "lo congelado no cambia")
        with self.assertRaises(self.access.MaskError):
            self.access.load_masks(self.project, self.v01.uid)

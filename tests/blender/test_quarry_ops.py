# SPDX-License-Identifier: GPL-3.0-or-later
"""Las órdenes de la cantera con dos superficies en Blender (spec 014; plan 014 §5.3.3, §5.5;
comprobación manual M1).

**«Límite desde el perímetro…»** (T20; HU-014-1; RF-014-01): la orden
``geoblender.des_create_limit_from_perimeter`` (``bl.ops.des``) calcula el **recinto excavable** de la
versión activa —el corte admitido de sus máscaras con dato en la superficie de partida— con
``design.steps.excavation_area_run``: **Calcular** lanza el modal por pasos (``_StepsModal``, con el
avance «Calculando el recinto excavable… 40 % · Esc: cancelar») hasta el resumen, sin registrar nada
(D-14 de la 013); **Crear** (la misma orden con ``confirm=True``) lo registra en una transacción como
``des_rcn_<nombre>`` con su área (``des.rcn_area_m2``); **Cancelar**, cerrar la ventana o Esc no dejan
nada. El cargador de ``des_rcn_`` (``bl.scene.des_views``) lo dibuja como objeto ``DESIGN`` sobre la
superficie de partida, y la barra N «Diseño» enseña su ficha.

Un proyecto por clase, pequeño y con las cifras a mano (ventana de 60 × 60 m con celdas de 2 m, V01 y
V02; el límite legal de (4, 4) a (52, 52) con 2 m hacia dentro, el perímetro de actuación de (2, 10) a
(56, 56) y una zona «sin corte» de (20, 20) a (30, 30) sin resguardo; una ladera ``100 + 0,25·y +
0,0625·x`` y una rejilla «sin dato» con dato solo en la primera columna, fuera del perímetro). El
recinto, a mano: los centros de celda con ``7 ≤ x ≤ 49`` e ``11 ≤ y ≤ 49`` (22 × 20 = 440 celdas)
menos las 5 × 5 de la zona sin corte, **415 celdas, 1.660 m²**; lo que lo separa del perímetro (621
celdas): 117 fuera del límite legal (468 m²), 64 del resguardo hacia dentro (256 m²) y 25 sin corte
(100 m²). Las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-014-01 (a): la orden es la real (con la puerta de la procedencia y los pasos con Esc) de
  ``des.excavation_area``; su diálogo pide el nombre y la superficie de partida y propone el terreno
  (T45 de la 013); el de la confirmación propone «Crear».
- RF-014-01, D-14 (b; M1): Calcular da el resumen («Recinto «Límite»: 415 celdas (1660 m²)») sin
  registrar nada; Crear registra la operación, el dato (1 en las 415 celdas a mano, sin dato fuera),
  su cifra (1.660 m² a ≤ 10⁻⁹ relativo), sus ajustes y sus entradas; cada llamada del modal dura menos
  de 0,2 s; el resumen y el avance, en los dos idiomas.
- RF-014-01 (c): un recinto vacío se rechaza nombrando la versión y el área de cada parte que lo vacía,
  en los dos idiomas, y no deja nada.
- D-14 (d): Esc a mitad, con el temporal ya escrito, «Cancelar» la confirmación y un nombre que falta
  no dejan nada.
- RF-014-01 (e; M1): cargar ``des_rcn_límite`` da un objeto ``DESIGN`` «Recinto excavable …» con un
  vértice en el centro de cada celda del recinto a la cota de la superficie de partida (relativo al
  GeoOrigin, matriz identidad); la barra N enseña su ficha (su superficie de partida y su cifra, sin las
  semillas de una envolvente); el diálogo sigue proponiendo el terreno, no el recinto.
**«Cantera con dos superficies…»** (T21; HU-014-3; RF-014-12, RF-014-13, RF-014-29, RF-014-30): la
orden ``geoblender.des_design_quarry`` calcula las dos superficies de la versión activa
(``des.quarry``) con ``design.steps.quarry_run``, con el mismo Calcular, Crear y Esc. El proyecto de la
clase lleva además dos sectores de búsqueda («Sector oeste», de x = 0 a 30 m, con la búsqueda cerrada,
y «Sector este», de 30 a 60 m, pendiente hasta la prueba h), los perfiles ``EXPL_10_60_6`` y
``REST_5_35_6`` y tres capas: los fondos (un polígono de (12, 16) a (24, 40) con ``cota`` 100 m), los
corredores (un eje de (36, 20) a (36, 44) con ``ancho`` 4 m y ``cota`` 104 m) y las zonas de
restauración por relleno (de (40, 30) a (48, 46)).

- RF-014-12 (f; plan §5.3.3, §5.5): la orden es la real, con la puerta de la procedencia y los pasos
  con Esc; su diálogo tiene arriba el nombre, la superficie de partida (propone el terreno: T45 de la
  013) y el orden, una caja por superficie (semillas, perfil base y el de cada sector, ancla y
  métrica) y abajo las capas con sus campos y «explotación hasta la final»; la confirmación dice
  «Crear» o «Crear con N avisos».
- RF-014-12, RF-014-13 (g): lo pedido en el diálogo es la ``QuarryRequest`` que se escribe a mano
  (los dos lados, los dos órdenes, cada capa con su campo, la rasante del corredor, la zona a
  conservar, el modo «capa»), y lo que falta se dice sin calcular.
- RF-014-30 (h): con el «Sector este» sin búsqueda vigente se niega a calcular nombrándolo y no deja
  nada.
- RF-014-12 a RF-014-14, RF-014-29 (i; M3): Calcular da el resumen de las dos superficies sin
  registrar nada (cinco temporales); Crear registra la operación con los ajustes de lo pedido, sus
  siete salidas y sus cifras; con los dos órdenes, ``final ≤ explotación ≤ terreno``, fuera del recinto
  la ladera, y la regla de orden a mano entre las dos canteras: ``explotación(final primero) =
  máx(explotación(explotación primero), final(final primero))`` y ``final(explotación primero) =
  mín(final(final primero), explotación(explotación primero))``, bit a bit.
- D-14 de la 013, RNF-014-05 (j): Esc a mitad (también con los temporales escritos), «Cancelar» la
  confirmación y un nombre que falta no dejan nada.
- Principio 8 (z): desactivar Geoblender quita las dos órdenes y el cargador y descarta el cálculo
  abierto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
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
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

LIMIT = "geoblender.des_create_limit_from_perimeter"
LIMIT_CLASS = "GEOBLENDER_OT_des_create_limit_from_perimeter"
LOAD = "geoblender.core_load_into_view"
PANEL = "GEOBLENDER_PT_des_design"
VIEW_PROPERTY = "geoblender_design"
AREA_TYPE = "des.excavation_area"
AREA_FIGURE = "des.rcn_area_m2"
KIND = "DESIGN"
REASON = "Prueba de «Límite desde el perímetro…»"
PERSON = "Samuel (IMGA)"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 10.0, 56.0, 56.0)
NO_CUT = (20.0, 20.0, 30.0, 30.0)
NAME = "Límite"
AREA_CELLS = 415
AREA_M2 = 1_660.0
PROPERTIES = {
    "name": ("Name", "Name of the excavation boundary, unique in the active version"),
    "surface": ("Start surface", "Ground of the project or of the active version: its cells "
                                 "without data stay out of the excavation boundary"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción."""
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 5_000

# «Cantera con dos superficies…» (T21).
QUARRY = "geoblender.des_design_quarry"
QUARRY_CLASS = "GEOBLENDER_OT_des_design_quarry"
QUARRY_TYPE = "des.quarry"
QUARRY_NAME = "Corta"
SECOND_NAME = "Corta B"
EXPL, REST = "EXPL_10_60_6", "REST_5_35_6"
EXPL_CODE, REST_CODE = "expl_10_60_6", "rest_5_35_6"
SOURCE = "Plan de explotación"
SECTORS = {"Sector oeste": (0.0, 0.0, 30.0, 60.0), "Sector este": (30.0, 0.0, 60.0, 60.0)}
SEARCH_DISTANCE_M = 25.0
CLOSED_AT = "2026-11-12T10:00:00Z"
LAYERS_TYPE = "gis.test_layers"
FLOORS_LAYER = "gis_fea_fondos"
FLOOR_BOX = (12.0, 16.0, 24.0, 40.0)
FLOOR_M = 100.0
CORRIDORS_LAYER = "gis_fea_corredores"
CORRIDOR_AXIS = ((36.0, 20.0), (36.0, 44.0))
CORRIDOR_WIDTH_M = 4.0
CORRIDOR_M = 104.0
FILL_LAYER = "gis_fea_relleno"
FILL_BOX = (40.0, 30.0, 48.0, 46.0)
QUARRY_FAMILIES = ("exp", "fin", "xen", "fen", "cls", "bmt", "qrp")
"""Las siete salidas de ``des.quarry`` (plan 014 §5.2.3): las dos superficies, sus envolventes, la
clasificación, las bermas de las dos y el informe."""
QUARRY_TEMPORARIES = 5
"""Las rejillas que «Calcular» deja en temporales (las dos tablas se preparan en memoria)."""
QUARRY_PROPERTIES = {
    "name": ("Name", "Name of the quarry, unique in the active version"),
    "order": ("Order of the design", "Final surface first: the final surface is computed first "
                                     "and the exploitation surface is raised where it is under "
                                     "it; exploitation surface first: the exploitation surface is "
                                     "computed first and the final surface is lowered where it is "
                                     "over it"),
    "final_seeds": ("Seeds of the final surface",
                    "Where the seeds of the final surface come from: the crown of the excavation "
                    "boundary and the zones to hold, or the seeds of a surface, a fixed elevation "
                    "or a grid of elevations"),
    "exploitation_anchor": ("Anchor of the exploitation surface",
                            "Elevation the benches of the exploitation surface are anchored to: "
                            "that of each profile, a grid of anchor elevations or the floor "
                            "nearest to each wall"),
    "to_final": ("Exploitation down to the final surface",
                 "Where the exploitation surface is lowered down to the final surface with its "
                 "benches: nowhere, in every warned zone or in the zones of a layer of polygons"),
}
"""Algunas propiedades del diálogo de la cantera con el ``msgid`` de su nombre y de su
descripción (todas llevan los dos)."""


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


def centers() -> tuple[np.ndarray, np.ndarray]:
    """Los centros de celda locales ``(x, y)`` de la ventana (fila 0 al norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    x = STEP_M * index + STEP_M / 2
    y = SIZE_M - (STEP_M * index + STEP_M / 2)
    return np.meshgrid(x, y)


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (exacta en binario)."""
    x, y = centers()
    return 100.0 + 0.25 * y + 0.0625 * x


def hand_area() -> np.ndarray:
    """El recinto a mano (véase el módulo): dentro del límite menos su resguardo de 2 m, dentro del
    perímetro y fuera de la zona sin corte."""
    x, y = centers()
    inner = (x >= 7) & (x <= 49) & (y >= 11) & (y <= 49)
    no_cut = (x >= 21) & (x <= 29) & (y >= 21) & (y <= 29)
    return inner & ~no_cut


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class LimitFromPerimeterTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, la ladera y la
    rejilla «sin dato», para toda la clase (las pruebas, en el orden de sus letras: cada una parte de
    lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t20-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.views = _module("bl.scene.views")
        cls.mesh = _module("bl.scene.mesh")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.dmodel = _module("design.model")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        cls.model = _module("core.project.model")
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
        cls.close_search("sector_1")  # el «Sector este», pendiente: lo cierra la prueba h
        cls.ground = cls.write_grid("Ladera", ground())
        hollow = np.full((CELLS, CELLS), np.nan)
        hollow[:, 0] = 100.0  # solo la primera columna, fuera del perímetro de actuación
        cls.hollow = cls.write_grid("Sin dato", hollow)
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.write_layer(FLOORS_LAYER, "polygon", ((ring(FLOOR_BOX),),), {"cota": FLOOR_M})
        cls.write_layer(CORRIDORS_LAYER, "line", ((path(CORRIDOR_AXIS),),),
                        {"ancho": CORRIDOR_WIDTH_M, "cota": CORRIDOR_M})
        cls.write_layer(FILL_LAYER, "polygon", ((ring(FILL_BOX),),), {})
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
        cls.refresh_lists()
        cls.dataset = cls.dprov.dataset_name("rcn", NAME)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y una zona sin corte (sin
        resguardo), como las dejará la orden de la 012."""
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
        """Los dos sectores de búsqueda (``core_sector``), como los dejará «Declarar de nuevo desde
        una capa…»."""
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
        """Cierra la búsqueda de intocables del sector ``code`` (con su huella), como la orden de
        la 012."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, code,
                                         cls.cstore.sector_sha256(sector), SEARCH_DISTANCE_M,
                                         PERSON, CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_layer(cls, name: str, kind: str, entity: tuple[tuple[np.ndarray, ...], ...],
                    numbers: dict[str, float]) -> None:
        """Una capa ``gis_fea_…`` de UNA entidad (sus partes con sus anillos o su camino,
        absolutos) con el campo ``nombre`` y los campos numéricos ``numbers`` (``DOUBLE``), como la
        deja la importación de la 006."""
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
    def refresh_lists(cls) -> None:
        """Las listas de los diálogos (perfiles, sectores, superficies, zonas y capas), leídas de
        nuevo (un guion no abre el diálogo que las lee)."""
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)

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

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no pasa a la siguiente

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(LIMIT)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operations(self, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, settings FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", AREA_TYPE)
        return self.rows(sql + " AND status = ? ORDER BY fid", AREA_TYPE, status)

    def datasets(self) -> list[str]:
        """Los recintos vivos del proyecto."""
        return [name for (name,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name LIKE 'des!_rcn!_%' ESCAPE '!' AND status = "
            "'current' ORDER BY name")]

    def names(self) -> list[str]:
        """Todos los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def temporaries(self) -> list[str]:
        """Los temporales que esperan junto a su destino (``*.tmp-*``)."""
        return [name for name in self.names() if ".tmp" in name]

    def nothing_left(self, files: list[str], done: int) -> None:
        """Ni una operación más del recinto, ni una en curso, ni un dato, una cifra o un fichero
        nuevos, ni un cálculo abierto."""
        self.assertEqual(len(self.operations("done")), done)
        self.assertEqual(self.operations("running"), [])
        self.assertEqual(len(self.datasets()), done)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key = ?", AREA_FIGURE),
                         [(done,)])
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)
        self.assertIsNone(self.des_ops.calculation())

    def running(self) -> Any:
        """El modal de la orden en marcha (el único con pasos)."""
        cls = self.cls
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{LIMIT} no está en marcha")
        return found[0]

    def drive(self, operator: Any, *, stop_after: int | None = None,
              until: Any = None) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba (o ``stop_after`` eventos,
        o hasta que ``until()`` sea verdad): su final y lo que duró cada llamada (s de CPU del
        proceso)."""
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
        """Lo pedido en el diálogo: el recinto «Límite» sobre la ladera."""
        return {"name": NAME, "surface": self.ground, "in_steps": True, **values}

    def start(self, **values: Any) -> Any:
        """Lanza la orden desde la interfaz (por pasos) y devuelve el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **self.form(**values)), {"RUNNING_MODAL"})
        return self.running()

    def calculate(self, **values: Any) -> tuple[set[str], list[float], Any]:
        """Calcula por pasos hasta el final (la confirmación, sustituida: sin ventana, el
        temporizador no corre): el final del modal, lo que duró cada llamada y el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            self.assertEqual(bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **self.form(**values)), {"RUNNING_MODAL"})
            modal = self.running()
            state, calls = self.drive(modal)
        self.assertEqual(ask.call_count, 1 if state == {"FINISHED"} else 0)
        if state == {"FINISHED"}:
            self.assertEqual(ask.call_args.kwargs.get("idname"), LIMIT)
        return state, calls, modal

    def create(self) -> set[str]:
        """«Crear»: la misma orden con ``confirm=True``."""
        return bpy.ops.geoblender.des_create_limit_from_perimeter("EXEC_DEFAULT", confirm=True,
                                                                  in_steps=True)

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana)."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "surface": "", "confirm": False, "in_steps": False,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        fake = operator_self(self.cls, report=lambda kind, text: None, **fields)
        return fake, context, dialog

    # --- Ayudas de la cantera (T21) -----------------------------------------------------------

    @property
    def quarry_cls(self) -> Any:
        return self.commands.registered_class(QUARRY)

    def quarry_operations(self, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, settings FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", QUARRY_TYPE)
        return self.rows(sql + " AND status = ? ORDER BY fid", QUARRY_TYPE, status)

    def quarry_datasets(self) -> list[str]:
        """Las salidas vivas de las canteras del proyecto."""
        return [name for (name,) in self.rows(
            "SELECT d.name FROM gb_dataset AS d JOIN gb_operation_io AS io ON io.item_uid = d.uid "
            "JOIN gb_operation AS o ON o.uid = io.operation_uid WHERE o.op_type = ? AND "
            "io.direction = 'out' AND d.status = 'current' ORDER BY d.name", QUARRY_TYPE)]

    def nothing_left_quarry(self, files: list[str], done: int) -> None:
        """Ni una cantera más, ni una en curso, ni una salida o un fichero nuevos, ni un cálculo
        abierto."""
        self.assertEqual(len(self.quarry_operations("done")), done)
        self.assertEqual(self.quarry_operations("running"), [])
        self.assertEqual(len(self.quarry_datasets()), done * len(QUARRY_FAMILIES))
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)
        self.assertIsNone(self.des_ops.calculation())

    def quarry_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: la cantera «Corta» sobre la ladera, la final con
        ``REST_5_35_6`` y la explotación con ``EXPL_10_60_6`` anclada al fondo de cada muro, con
        los fondos, el corredor de cota fija y las zonas de relleno (los campos, los propuestos)."""
        return {"name": QUARRY_NAME, "start": self.ground, "final_profile": REST,
                "exploitation_profile": EXPL, "exploitation_anchor": "NEAREST_FLOOR",
                "floors_layer": FLOORS_LAYER, "corridors_layer": CORRIDORS_LAYER,
                "corridors_level": "FIXED", "fill_layer": FILL_LAYER, "in_steps": True, **values}

    def quarry_request(self, name: str = QUARRY_NAME, order: str = "final_first") -> Any:
        """La ``QuarryRequest`` de :meth:`quarry_form`, escrita a mano."""
        m = self.dmodel
        return m.QuarryRequest(
            name, self.ground, m.QuarrySide(REST_CODE),
            m.QuarrySide(EXPL_CODE, anchor=m.AnchorMode.NEAREST_FLOOR), order=order,
            floors=m.LayerField(FLOORS_LAYER, "cota"),
            corridors=m.CorridorFields(CORRIDORS_LAYER, "ancho", level_field="cota"),
            fill_zones=FILL_LAYER)

    def quarry_running(self) -> Any:
        """El modal de la cantera en marcha (el único con pasos)."""
        cls = self.quarry_cls
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{QUARRY} no está en marcha")
        return found[0]

    def quarry_start(self, **values: Any) -> Any:
        """Lanza la cantera desde la interfaz (por pasos) y devuelve el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_design_quarry(
                "EXEC_DEFAULT", **self.quarry_form(**values)), {"RUNNING_MODAL"})
        return self.quarry_running()

    def quarry_calculate(self, **values: Any) -> tuple[set[str], list[float], Any]:
        """Calcula la cantera por pasos hasta el final (la confirmación, sustituida): el final del
        modal, lo que duró cada llamada y el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            self.assertEqual(bpy.ops.geoblender.des_design_quarry(
                "EXEC_DEFAULT", **self.quarry_form(**values)), {"RUNNING_MODAL"})
            modal = self.quarry_running()
            state, calls = self.drive(modal)
        self.assertEqual(ask.call_count, 1 if state == {"FINISHED"} else 0)
        if state == {"FINISHED"}:
            self.assertEqual(ask.call_args.kwargs.get("idname"), QUARRY)
        return state, calls, modal

    def quarry_create(self) -> set[str]:
        """«Crear» la cantera: la misma orden con ``confirm=True``."""
        return bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", confirm=True, in_steps=True)

    def quarry_fields(self, **values: Any) -> dict[str, Any]:
        """Todos los campos del diálogo de la cantera con lo que pone por defecto (sin la
        propuesta), cambiados por ``values``."""
        return {"name": "", "start": "none", "order": "FINAL_FIRST",
                "final_seeds": "CROWN", "final_surface": "none", "final_zone": "none",
                "final_elevation": "", "final_profile": "", "final_anchor": "FIXED",
                "final_anchor_grid": "none", "final_metric": "CHAMFER5",
                "exploitation_seeds": "CROWN", "exploitation_surface": "none",
                "exploitation_zone": "none", "exploitation_elevation": "",
                "exploitation_profile": "", "exploitation_anchor": "FIXED",
                "exploitation_anchor_grid": "none", "exploitation_metric": "CHAMFER5",
                "floors_layer": "none", "floors_field": "cota", "conserve": "none",
                "corridors_layer": "none", "corridors_width_field": "ancho",
                "corridors_level": "FIXED", "corridors_level_field": "cota",
                "corridors_start_field": "cota_inicial", "corridors_grade_field": "pendiente",
                "fill_layer": "none", "water_layer": "none", "water_field": "cota",
                "to_final": "NONE", "to_final_layer": "none", "confirm": False,
                "in_steps": False, **values}

    def read(self, family: str, name: str) -> np.ndarray:
        """Las cotas de la rejilla ``family`` de la cantera ``name`` de V01, releídas."""
        return self.surfaces.read_surface(self.project, self.dprov.dataset_name(family, name),
                                          version_uid=self.v01.uid).values

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_confirmation(self) -> None:
        """RF-014-01 (plan §5.3.3, §5.5): «Límite desde el perímetro…» es una orden real con la
        puerta de la procedencia y los pasos con Esc, de ``des.excavation_area``; su diálogo pide el
        nombre y la superficie de partida (propone «Recinto excavable» y el terreno, la primera que
        no es una rejilla de un diseño: T45 de la 013) y Calcular; el de la confirmación propone
        «Crear»; sus textos tienen su español."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (AREA_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[AREA_TYPE].commands, (LIMIT,))
        cat = self.commands.catalog()
        self.assertEqual(cat.commands[LIMIT].label_es, "Límite desde el perímetro…")
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])

        fake, context, dialog = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Límite desde el perímetro…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual(fake.name, "Recinto excavable")
        self.assertEqual(fake.surface, self.ground)  # el terreno, no «Sin dato»
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        self.assertEqual(listed[:2], [self.ground, self.hollow])  # y las máscaras, como en la 013
        shown = draw(cls, bpy.context, name="", surface=self.ground, confirm=False).texts()
        for heading in ("Nombre", "Superficie de partida"):
            self.assertIn(heading, shown)
        given, _context, _dialog = self.fake_dialog(
            name="Mío", surface=self.hollow,
            properties=SimpleNamespace(is_property_set=lambda name: name == "surface"))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.surface), ("Mío", self.hollow))  # lo dado no cambia

        # La confirmación: sin cálculo abierto se niega; con él, «Crear».
        reports: list[tuple[Any, str]] = []
        fake.confirm = True
        fake.report = lambda kind, text: reports.append((kind, text))
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports[-1][1], "No hay un cálculo abierto: calcule antes")
        held = SimpleNamespace(open=True, warnings=lambda: (), op_type=AREA_TYPE,
                               discard=lambda: None)
        with mock.patch.object(self.des_ops, "calculation", return_value=held):
            dialog.reset_mock()
            self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Crear")

    def test_b_calculate_then_create_the_excavation_boundary(self) -> None:
        """RF-014-01, D-14 de la 013 (M1): Calcular el recinto «Límite» de V01 sobre la ladera da el
        resumen (415 celdas, 1.660 m²) y deja el temporal sin registrar nada; Crear registra la
        operación hecha, el dato ``des_rcn_límite`` (1 en las 415 celdas a mano y sin dato en las
        demás), su cifra CALCULADO (1.660 m² a ≤ 10⁻⁹ relativo), sus ajustes (nombre y superficie de
        partida) y sus entradas (la superficie y las máscaras), apuntada para Ctrl+Z. Cada llamada del
        modal dura menos de 0,2 s; el avance y el resumen, en los dos idiomas (principio 10)."""
        files = self.names()
        self.i18n.set_language("en")
        state, _calls, modal = self.calculate(name="Pit")
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.view.summary_title, "Excavation boundary «Pit» in V01")
        self.assertRegex(self.view.summary[0].name,
                         r"^Excavation boundary «Pit»: 415 cells \(1\D?660 m²\)$")
        self.assertEqual(modal._status_text(self.model.Progress("area", 2, 5, "…")),
                         "Computing the excavation boundary… 40 % · Esc: cancel")
        self.des_ops.discard_calculation()
        self.nothing_left(files, 0)
        self.i18n.set_language("es")

        state, calls, modal = self.calculate()
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual(modal._status_text(self.model.Progress("area", 2, 5, "…")),
                         "Calculando el recinto excavable… 40 % · Esc: cancelar")
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.version, held.open),
                         (AREA_TYPE, NAME, "V01", True))
        self.assertEqual(self.operations(), [])  # sin registrar (D-14)
        self.assertEqual(self.datasets(), [])
        self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual(self.view.summary_title, "Recinto excavable «Límite» en V01")
        lines = [(item.name, item.alert) for item in self.view.summary]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0][0], r"^Recinto excavable «Límite»: 415 celdas \(1\D?660 m²\)$")
        self.assertFalse(lines[0][1])

        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no deshace la base: apuntada
        self.assertEqual(journal.entries[-1].label, AREA_TYPE)
        ((uid, _status, settings),) = self.operations("done")
        self.assertEqual(json.loads(settings), {"name": NAME, "surface": self.ground})
        self.assertEqual(self.datasets(), [self.dataset])
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.view.summary_title, "")
        ((figure, kind),) = self.rows("SELECT value, kind FROM gb_figure WHERE operation_uid = ? "
                                      "AND key = ?", uid, AREA_FIGURE)
        self.assertEqual(kind, "CALCULADO")
        self.assertLessEqual(abs(figure - AREA_M2) / AREA_M2, 1e-9)
        roles = {role: name for name, role in self.rows(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset'", uid)}
        self.assertEqual(roles.get("surface"), self.ground)
        self.assertGreater(len(roles), 1)  # y las máscaras de V01
        raster = self.surfaces.read_surface(self.project, self.dataset, version_uid=self.v01.uid)
        wanted = hand_area()
        self.assertEqual(int(np.count_nonzero(wanted)), AREA_CELLS)
        self.assertTrue(np.array_equal(np.isfinite(raster.values), wanted))
        self.assertTrue(np.all(raster.values[wanted] == 1.0))
        self.assertTrue(set(files) <= set(self.names()))  # nada se borró

    def test_c_an_empty_boundary_is_refused_with_what_empties_it(self) -> None:
        """RF-014-01 (casos límite de la spec): sobre la rejilla «sin dato» el recinto queda vacío y
        se rechaza al calcular, nombrando la versión y el área de cada parte que lo vacía (fuera del
        límite legal 468 m², resguardo hacia dentro 256 m², sin corte 100 m², sin dato de terreno
        1.660 m²), desde la interfaz y desde un guion, en los dos idiomas; no deja nada."""
        files = self.names()
        done = len(self.operations("done"))
        parts = ("perímetro fuera del límite legal: 468 m²", "resguardo hacia dentro del límite: "
                 "256 m²", "zonas sin corte, solo relleno o solo restauración: 100 m²")
        modal = self.start(name="Vacío", surface=self.hollow)
        state, _calls = self.drive(modal)
        self.assertEqual(state, {"CANCELLED"})
        shown = " ".join(modal.report_log)
        self.assertIn("El recinto excavable de la versión V01 está vacío", shown)
        for part in parts:
            self.assertIn(part, shown)
        self.assertRegex(shown, r"sin dato de terreno: 1\D?660 m²")
        self.nothing_left(files, done)
        self.i18n.set_language("en")
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", name="Vacío", surface=self.hollow)
        self.assertIn("The excavation area of version V01 is empty", str(raised.exception))
        self.nothing_left(files, done)

    def test_d_esc_cancel_and_a_missing_field_leave_nothing(self) -> None:
        """D-14 de la 013 (M1): Esc a mitad de calcular, también con el temporal ya escrito,
        «Cancelar» la confirmación (``cancel``) y un nombre o una superficie que faltan no dejan
        nada: ni operaciones, ni datos, ni cifras, ni ficheros, ni cálculo abierto. La ventana del
        cálculo, cerrada, no descarta lo ya abierto."""
        files = self.names()
        done = len(self.operations("done"))
        with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):
            for label, events in (("al empezar", 1), ("con el temporal escrito", None)):
                with self.subTest(momento=label):
                    modal = self.start(name="Esc")
                    if events is None:
                        self.drive(modal, until=lambda: bool(self.temporaries()))
                        self.assertTrue(self.temporaries(), "no llegó a escribir el temporal")
                    else:
                        self.drive(modal, stop_after=events)
                    self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                    self.assertIsNone(modal._steps)
                    self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                    self.nothing_left(files, done)
        state, _calls, _modal = self.calculate(name="Descartado")
        self.assertEqual(state, {"FINISHED"})
        form = operator_self(self.cls, confirm=False, in_steps=False)
        self.cls.cancel(form, bpy.context)  # la ventana del cálculo: lo abierto sigue
        self.assertIsNotNone(self.des_ops.calculation())
        confirmation = operator_self(self.cls, confirm=True, in_steps=False)
        self.cls.cancel(confirmation, bpy.context)  # «Cancelar» o cerrar la ventana
        self.nothing_left(files, done)
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **{**self.form(in_steps=False), "name": " "})
        self.assertIn("Escriba el nombre del recinto excavable", str(raised.exception))
        self.nothing_left(files, done)
        reports: list[str] = []
        fake = operator_self(self.cls, name=NAME, surface="none", confirm=False, in_steps=False,
                             provenance_dialog=False,
                             report=lambda kind, text: reports.append(text))
        self.assertEqual(self.cls.execute(fake, bpy.context), {"CANCELLED"})  # sin superficies
        self.assertEqual(reports, ["Elija la superficie de partida del recinto excavable"])
        self.nothing_left(files, done)
        with self.assertRaises(RuntimeError) as raised:
            self.create()
        self.assertIn("No hay un cálculo abierto", str(raised.exception))

    def test_e_the_boundary_in_the_view_and_its_card(self) -> None:
        """RF-014-01 (M1), ADR-0005: «Cargar en la vista» del recinto da un objeto ``DESIGN``
        «Recinto excavable … · V01 [VIGENTE]» con matriz identidad y un vértice en el centro de cada
        una de las 415 celdas del recinto (y de ninguna otra), a la cota de la ladera de su
        partida; no escribe nada en el proyecto. Seleccionado, la barra N «Diseño» enseña su ficha:
        su título, su superficie de partida y su cifra, sin las semillas ni la envolvente de una
        envolvente. El diálogo sigue proponiendo la ladera como terreno, no el recinto."""
        (uid,) = [row[0] for row in self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND "
                                              "status = 'current'", self.dataset)]
        loader = self.views.loader_for(self.dataset)
        self.assertEqual((loader.prefix, loader.kind, loader.label),
                         ("des_rcn_", KIND, "Excavation boundary"))
        files = self.names()
        operations = self.rows("SELECT count(*) FROM gb_operation")
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
        self.assertEqual((self.names(), self.rows("SELECT count(*) FROM gb_operation")),
                         (files, operations))
        (obj,) = [item for item in bpy.data.objects if item.geoblender.dataset_uid == uid]
        self.assertEqual(obj.geoblender.kind, KIND)
        self.assertTrue(obj.name.startswith("Recinto excavable "), obj.name)
        self.assertTrue(obj.name.endswith(" · V01 [VIGENTE]"), obj.name)
        self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))  # nunca el origen en location
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        world = self.mesh.mesh_vertices_world(obj.data, self.project.origin)
        grid = _module("gis.grid").project_grid(self.project.record.window, STEP_M)
        columns = (world[:, 0] - grid.west) / grid.dx - 0.5
        rows = (grid.north - world[:, 1]) / grid.dy - 0.5
        np.testing.assert_allclose(columns, np.rint(columns), atol=1e-6)  # centros de celda
        np.testing.assert_allclose(rows, np.rint(rows), atol=1e-6)
        cells = np.zeros((CELLS, CELLS), dtype=bool)
        cells[np.rint(rows).astype(int), np.rint(columns).astype(int)] = True
        self.assertTrue(np.array_equal(cells, hand_area()))
        heights = ground()[np.rint(rows).astype(int), np.rint(columns).astype(int)]
        np.testing.assert_allclose(world[:, 2], heights, atol=1e-4)

        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        self.assertEqual((self.view.item_uid, self.view.item_found), (uid, True))
        self.assertEqual(self.view.item_title, f"Recinto excavable · {NAME}")
        texts = [row.name for row in self.view.item]
        self.assertIn(f"Superficie de partida: «{self.ground}»", texts)
        self.assertNotIn("Semillas y dominios", texts)
        self.assertFalse(any(text.startswith("Envolvente") for text in texts), texts)
        self.assertTrue(any("[CAL]" in text and "Área del recinto" in text for text in texts),
                        texts)
        self.assertTrue(getattr(bpy.types, PANEL).poll(bpy.context))

        fake, context, _dialog = self.fake_dialog()
        self.assertEqual(self.cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        self.assertIn(self.dataset, listed)
        self.assertEqual(listed[0], self.dataset)  # el primero de la lista…
        self.assertEqual(fake.surface, self.ground)  # …pero se propone el terreno
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()

    def test_f_the_quarry_command_its_dialog_and_the_confirmation(self) -> None:
        """RF-014-12 (plan §5.3.3, §5.5): «Cantera con dos superficies…» es una orden real con la
        puerta de la procedencia y los pasos con Esc, de ``des.quarry``; todas sus propiedades
        tienen nombre y descripción en español; su diálogo propone «Cantera» y, de partida, el
        terreno (T45 de la 013), y dibuja arriba el nombre, la partida y el orden, una caja por
        superficie con sus semillas, su perfil base, el de cada sector, su ancla y su métrica, y
        abajo las capas con sus campos y «explotación hasta la final»; la confirmación propone
        «Crear» o «Crear con N avisos»."""
        cls = self.quarry_cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (QUARRY_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[QUARRY_TYPE].commands, (QUARRY,))
        self.assertEqual(self.commands.catalog().commands[QUARRY].label_es,
                         "Cantera con dos superficies…")
        for prop, (label, about) in QUARRY_PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        fields = self.quarry_fields()
        for prop in fields:
            if prop in ("confirm", "in_steps"):
                continue
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertTrue(keywords.get("name") and keywords.get("description"), prop)

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fake = operator_self(self.quarry_cls, report=lambda kind, text: None, **self.quarry_fields(
            properties=SimpleNamespace(is_property_set=lambda name: False)))
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Cantera con dos superficies…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.start), ("Cantera", self.ground))  # el terreno (T45)
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        self.assertEqual(listed[0], self.dataset)  # el recinto va primero, pero no se propone
        given = operator_self(self.quarry_cls, report=lambda kind, text: None, **self.quarry_fields(
            name="Mía", start=self.hollow,
            properties=SimpleNamespace(is_property_set=lambda name: name == "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.start), ("Mía", self.hollow))  # lo dado no cambia
        lines = [item[0] for item in self.panels.line_layer_items(None, None)]
        self.assertEqual(lines, ["none", CORRIDORS_LAYER])  # solo las capas de líneas
        polygons = [item[0] for item in self.panels.optional_layer_items(None, None)]
        self.assertEqual(polygons, ["none", FLOORS_LAYER, FILL_LAYER])
        conserve = [item[0] for item in self.panels.conserve_items(None, None)]
        self.assertEqual(conserve[0], "none")
        self.assertIn(f"layer:{FILL_LAYER}", conserve)
        self.assertTrue(any(item.startswith("constraint:") for item in conserve))

        shown = draw(cls, bpy.context, **self.quarry_fields(
            floors_layer=FLOORS_LAYER, corridors_layer=CORRIDORS_LAYER, water_layer=FLOORS_LAYER,
            to_final="LAYER")).texts()
        for heading in ("Nombre", "Superficie de partida", "Orden del diseño", "Superficie final",
                        "Superficie de explotación", "Capas", "Fondos", "Campo de cota",
                        "Zona a conservar", "Corredores", "Campo del ancho",
                        "Zonas de restauración por relleno", "Láminas de agua",
                        "Explotación hasta la final", "Capa de las zonas", "Sector oeste"):
            with self.subTest(texto=heading):
                self.assertIn(heading, shown)
        for twice in ("Origen de las semillas", "Perfil base", "Ancla", "Métrica", "Sector este",
                      "Búsqueda pendiente"):  # en la caja de cada superficie
            with self.subTest(texto=twice):
                self.assertEqual(shown.count(twice), 2)
        texts = draw(cls, bpy.context, **self.quarry_fields(
            corridors_layer=CORRIDORS_LAYER, corridors_level="GRADE", final_seeds="FIXED",
            exploitation_anchor="GRID")).texts()
        for heading in ("Campo de la cota inicial", "Campo de la pendiente", "Cota (m)",
                        "Zona de las semillas", "Rejilla de cotas de ancla"):
            with self.subTest(texto=heading):
                self.assertIn(heading, texts)
        self.assertNotIn("Campo de cota", texts)  # sin fondos ni corredor de cota fija

        # La confirmación: sin cálculo abierto se niega; con él, «Crear» o «Crear con N avisos».
        reports: list[tuple[Any, str]] = []
        fake.confirm = True
        fake.report = lambda kind, text: reports.append((kind, text))
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports[-1][1], "No hay un cálculo abierto: calcule antes")
        for warnings, wanted in (((), "Crear"), (("uno", "dos"), "Crear con 2 avisos")):
            held = SimpleNamespace(open=True, warnings=lambda found=warnings: found,
                                   op_type=QUARRY_TYPE, discard=lambda: None)
            with mock.patch.object(self.des_ops, "calculation", return_value=held):
                dialog.reset_mock()
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
            self.assertEqual(dialog.call_args.kwargs["confirm_text"], wanted)

    def test_g_the_dialog_is_the_request(self) -> None:
        """RF-014-12, RF-014-13 (plan §5.3.3): lo pedido en el diálogo es la ``QuarryRequest`` que
        se escribe a mano —el orden, cada lado con sus semillas (coronación o las de la 013 con su
        zona), su perfil base y el de cada sector (por su nombre), su ancla (con su rejilla) y su
        métrica; los fondos y las láminas con su campo, la zona a conservar, el corredor con su
        rasante, las zonas de relleno y «explotación hasta la final» con su capa—; y lo que falta
        se dice en español sin calcular nada."""
        cls = self.quarry_cls
        (constraint,) = [item[0] for item in self.panels.conserve_items(None, None)
                         if item[1] == "Sin corte"]
        code = constraint.removeprefix("constraint:")
        east = [item for item in self.view.sectors if item.code == "sector_2"][0]
        east.final_pick = EXPL
        self.addCleanup(setattr, east, "final_pick", "")
        fields = self.quarry_fields(
            name=" Mía ", start=self.ground, order="EXPLOITATION_FIRST", final_profile=REST,
            final_metric="EXACT", exploitation_seeds="SURFACE", exploitation_surface=self.ground,
            exploitation_zone=constraint, exploitation_profile=EXPL, exploitation_anchor="GRID",
            exploitation_anchor_grid=self.hollow, floors_layer=FLOORS_LAYER,
            floors_field="cota", conserve=f"layer:{FILL_LAYER}", corridors_layer=CORRIDORS_LAYER,
            corridors_level="GRADE", fill_layer=FILL_LAYER, water_layer=FLOORS_LAYER,
            to_final="LAYER", to_final_layer=FILL_LAYER)
        found = cls._request(operator_self(cls, **fields), self.project)
        m = self.dmodel
        wanted = m.QuarryRequest(
            "Mía", self.ground,
            m.QuarrySide(REST_CODE, {"sector_2": EXPL_CODE}, metric=m.Metric.EXACT),
            m.QuarrySide(EXPL_CODE, seeds=m.SeedSource(
                m.SeedKind.SURFACE, surface=self.ground, zone=m.Zone(m.ZoneKind.CONSTRAINT, code)),
                anchor=m.AnchorMode.GRID, anchor_grid=self.hollow),
            order=m.Order.EXPLOITATION_FIRST, floors=m.LayerField(FLOORS_LAYER, "cota"),
            conserve=(m.Zone(m.ZoneKind.LAYER, FILL_LAYER),),
            corridors=m.CorridorFields(CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                       grade_field="pendiente"),
            fill_zones=FILL_LAYER, water=m.LayerField(FLOORS_LAYER, "cota"),
            to_final=m.ToFinalMode.LAYER, to_final_layer=FILL_LAYER)
        self.assertEqual(found, wanted)
        self.assertEqual(cls._request(operator_self(cls, **self.quarry_fields(
            name="Fija", start=self.ground, final_profile=REST, exploitation_profile=EXPL,
            final_seeds="FIXED", final_zone="domain", final_elevation="102,5",
            corridors_layer=CORRIDORS_LAYER)), self.project).final.seeds,
            m.SeedSource(m.SeedKind.FIXED, zone=m.Zone(m.ZoneKind.DOMAIN), elevation_m=102.5))

        good = self.quarry_fields(name="Corta", start=self.ground, final_profile=REST,
                                  exploitation_profile=EXPL)
        for change, message in (
                ({"name": " "}, "Escriba el nombre de la cantera"),
                ({"start": "none"}, "Elija la superficie de partida de la cantera"),
                ({"final_profile": ""}, "Elija el perfil base de «Superficie final»"),
                ({"exploitation_profile": "NO_EXISTE"}, "«NO_EXISTE»"),
                ({"exploitation_anchor": "GRID"},
                 "Elija la rejilla de cotas de ancla de «Superficie de explotación»"),
                ({"final_seeds": "FIXED", "final_zone": "domain"},
                 "Escriba la cota fija de las semillas en metros"),
                ({"floors_layer": FLOORS_LAYER, "floors_field": " "},
                 "Escriba el nombre del campo «Campo de cota» de la capa «fondos»"),
                ({"corridors_layer": CORRIDORS_LAYER, "corridors_width_field": ""},
                 "Escriba el nombre del campo «Campo del ancho» de la capa «corredores»"),
                ({"to_final": "LAYER"}, "Elija la capa de «Explotación hasta la final»")):
            with self.subTest(cambio=change):
                with self.assertRaises(self.des_ops.ComputeFormError) as raised:
                    cls._request(operator_self(cls, **{**good, **change}), self.project)
                self.assertIn(message, str(raised.exception))

    def test_h_a_sector_without_search_is_refused(self) -> None:
        """RF-014-30 (como RF-013-05): con el «Sector este» del recinto sin búsqueda de intocables
        vigente, la cantera se niega a calcular nombrándolo y nombrando la orden de la 012 que la
        busca, desde la interfaz y desde un guion, y no deja nada; con la búsqueda cerrada, ya
        calcula (prueba i)."""
        files = self.names()
        modal = self.quarry_start()
        state, _calls = self.drive(modal)
        self.assertEqual(state, {"CANCELLED"})
        shown = " ".join(modal.report_log)
        self.assertIn("sin búsqueda de intocables vigente", shown)
        self.assertIn("Sector este", shown)
        self.assertNotIn("Sector oeste", shown)
        self.assertIn("Buscar elementos intocables por sector…", shown)
        self.nothing_left_quarry(files, 0)
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT",
                                                 **self.quarry_form(in_steps=False))
        self.assertIn("Sector este", str(raised.exception))
        self.nothing_left_quarry(files, 0)
        self.close_search("sector_2")

    def test_i_calculate_then_create_with_both_orders(self) -> None:
        """RF-014-12 a RF-014-14, RF-014-29 (M3): Calcular la cantera «Corta» de V01 («final
        primero») da el resumen de las dos superficies (el orden con las celdas que cambió, las
        cotas de cada una, la excavación de la explotación, el desdoblado y el relleno) y deja sus
        cinco rejillas en temporales sin registrar nada; cada llamada del modal dura menos de 0,2 s;
        el resumen y el avance, en los dos idiomas. Crear registra la operación con los ajustes de
        lo pedido (la ``QuarryRequest`` a mano y los sectores que toca el recinto), sus siete
        salidas y sus cifras CALCULADO, apuntada para Ctrl+Z. «Corta B», con «explotación primero»,
        igual. Releídas: ``final ≤ explotación ≤ terreno`` en las dos, la ladera fuera del recinto y
        la regla de orden de RF-014-13 entre las dos canteras, bit a bit."""
        files = self.names()
        state, calls, modal = self.quarry_calculate()
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual(modal._status_text(self.model.Progress("quarry", 2, 5, "…")),
                         "Calculando la cantera… 40 % · Esc: cancelar")
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.version, held.open),
                         (QUARRY_TYPE, QUARRY_NAME, "V01", True))
        self.assertEqual(self.quarry_operations(), [])  # sin registrar (RF-014-29)
        self.assertEqual(len(self.temporaries()), QUARRY_TEMPORARIES)
        self.assertEqual(self.view.summary_title, "Cantera «Corta» en V01")
        lines = [item.name for item in self.view.summary]
        self.assertRegex(lines[0], r"^Orden del diseño: Primero la superficie final · la regla de "
                                   r"orden cambió \d[\d.]* celdas$")
        self.assertRegex(lines[1], r"^Superficie final: cotas \d")
        self.assertRegex(lines[2], r"^Superficie de explotación: cotas \d.* · excavación \d")
        self.assertRegex(lines[3], r"^Desdoblado \d.* m³ · relleno de restauración \d.* m³$")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, "Quarry «Corta» in V01")
        self.assertTrue(self.view.summary[0].name.startswith(
            "Order of the design: Final surface first · the order rule changed "),
            self.view.summary[0].name)
        self.assertEqual(modal._status_text(self.model.Progress("quarry", 2, 5, "…")),
                         "Computing the quarry… 40 % · Esc: cancel")
        self.i18n.set_language("es")

        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.quarry_create(), {"FINISHED"})
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no deshace la base: apuntada
        self.assertEqual(journal.entries[-1].label, QUARRY_TYPE)
        ((uid, _status, settings),) = self.quarry_operations("done")
        stored = json.loads(settings)
        self.assertEqual(self.dprov.quarry_request(stored), self.quarry_request())
        self.assertEqual((sorted(stored["touched_sectors"]), stored["pending_sectors"]),
                         (["sector_1", "sector_2"], []))
        self.assertEqual(sorted(self.quarry_datasets()), sorted(
            self.dprov.dataset_name(family, QUARRY_NAME) for family in QUARRY_FAMILIES))
        figures = self.rows("SELECT key, kind FROM gb_figure WHERE operation_uid = ?", uid)
        self.assertIn("des.exp_cut_m3", {key for key, _kind in figures})
        self.assertEqual({kind for _key, kind in figures}, {"CALCULADO"})
        self.assertEqual((self.temporaries(), self.des_ops.calculation(),
                          self.view.summary_title), ([], None, ""))

        state, _calls, _modal = self.quarry_calculate(name=SECOND_NAME,
                                                      order="EXPLOITATION_FIRST")
        self.assertEqual(state, {"FINISHED"})
        self.assertTrue(self.view.summary[0].name.startswith(
            "Orden del diseño: Primero la superficie de explotación"))
        self.assertEqual(self.quarry_create(), {"FINISHED"})
        self.assertEqual(json.loads(self.quarry_operations("done")[-1][2])["order"],
                         "exploitation_first")
        self.assertTrue(set(files) <= set(self.names()))  # nada se borró

        z = ground()
        inside = hand_area()  # el recinto: el dominio de las dos superficies
        final_a, exploitation_a = self.read("fin", QUARRY_NAME), self.read("exp", QUARRY_NAME)
        final_b, exploitation_b = self.read("fin", SECOND_NAME), self.read("exp", SECOND_NAME)
        for final, exploitation in ((final_a, exploitation_a), (final_b, exploitation_b)):
            self.assertTrue(np.array_equal(final[~inside], z[~inside]))  # fuera, la ladera
            self.assertTrue(np.array_equal(exploitation[~inside], z[~inside]))
            self.assertTrue(np.all(final[inside] <= exploitation[inside] + 1e-3))  # RF-014-14
            self.assertTrue(np.all(exploitation[inside] <= z[inside] + 1e-3))
        self.assertTrue(np.any(exploitation_a != exploitation_b))  # el orden cambia algo…
        self.assertTrue(np.any(final_a != final_b))
        self.assertTrue(np.array_equal(exploitation_a, np.maximum(exploitation_b, final_a)))
        self.assertTrue(np.array_equal(final_b, np.minimum(final_a, exploitation_b)))
        classes = self.read("cls", QUARRY_NAME)
        self.assertTrue(np.all(np.isnan(classes[~inside])))
        self.assertTrue(set(np.unique(classes[inside]).tolist()) <= {0.0, 1.0, 2.0})

    def test_j_esc_cancel_and_a_missing_field_leave_nothing(self) -> None:
        """D-14 de la 013, RNF-014-05, RF-014-29: Esc a mitad de calcular la cantera, también con
        los temporales ya escritos, «Cancelar» la confirmación y un nombre que falta no dejan nada:
        ni operaciones, ni salidas, ni ficheros, ni cálculo abierto; la ventana del cálculo,
        cerrada, no descarta lo ya abierto."""
        files = self.names()
        done = len(self.quarry_operations("done"))
        with mock.patch.object(self.quarry_cls, "STEP_BUDGET_S", 1e-9):
            for label, events in (("al empezar", 1), ("con los temporales escritos", None)):
                with self.subTest(momento=label):
                    modal = self.quarry_start(name="Esc")
                    if events is None:
                        self.drive(modal, until=lambda: bool(self.temporaries()))
                        self.assertTrue(self.temporaries(), "no llegó a escribir un temporal")
                    else:
                        self.drive(modal, stop_after=events)
                    self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                    self.assertIsNone(modal._steps)
                    self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                    self.nothing_left_quarry(files, done)
        state, _calls, _modal = self.quarry_calculate(name="Descartada")
        self.assertEqual(state, {"FINISHED"})
        form = operator_self(self.quarry_cls, confirm=False, in_steps=False)
        self.quarry_cls.cancel(form, bpy.context)  # la ventana del cálculo: lo abierto sigue
        self.assertIsNotNone(self.des_ops.calculation())
        confirmation = operator_self(self.quarry_cls, confirm=True, in_steps=False)
        self.quarry_cls.cancel(confirmation, bpy.context)  # «Cancelar» o cerrar la ventana
        self.nothing_left_quarry(files, done)
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_design_quarry(
                "EXEC_DEFAULT", **{**self.quarry_form(in_steps=False), "name": " "})
        self.assertIn("Escriba el nombre de la cantera", str(raised.exception))
        self.nothing_left_quarry(files, done)
        with self.assertRaises(RuntimeError) as raised:
            self.quarry_create()
        self.assertIn("No hay un cálculo abierto", str(raised.exception))

    def test_z_disabling_geoblender_removes_the_command_and_the_loader(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta (no
        queda ningún temporal) y quita las dos órdenes y el cargador del recinto."""
        state, _calls, _modal = self.calculate(name="Al apagar")
        self.assertEqual(state, {"FINISHED"})
        self.assertTrue(self.temporaries())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, LIMIT_CLASS, None))
        self.assertIsNone(getattr(bpy.types, QUARRY_CLASS, None))
        self.assertIsNone(self.views.loader_for(self.dataset))
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())


if __name__ == "__main__":
    unittest.main()
